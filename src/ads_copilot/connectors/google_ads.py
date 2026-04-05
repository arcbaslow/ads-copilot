"""Google Ads API connector (v18+).

Wraps the official google-ads Python client in an async-friendly facade that
matches the AdPlatformConnector protocol. The underlying client is sync; we
run its calls in a thread executor so we don't block the event loop.

Auth: expects a google-ads.yaml with developer_token, client_id, client_secret,
refresh_token, and login_customer_id. Or the equivalent env vars.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ads_copilot.connectors.base import ConnectorError
from ads_copilot.models import (
    AdGroupData,
    AdGroupNode,
    CampaignData,
    CampaignNode,
    CampaignStatus,
    CampaignTree,
    ConversionData,
    DateRange,
    KeywordNode,
    MatchType,
    Metrics,
    MutateResult,
    NegativeKeyword,
    Platform,
    SearchQueryData,
)

if TYPE_CHECKING:
    from google.ads.googleads.client import GoogleAdsClient

log = logging.getLogger(__name__)


_STATUS_MAP = {
    "ENABLED": CampaignStatus.ENABLED,
    "PAUSED": CampaignStatus.PAUSED,
    "REMOVED": CampaignStatus.REMOVED,
    "UNKNOWN": CampaignStatus.UNKNOWN,
    "UNSPECIFIED": CampaignStatus.UNKNOWN,
}

_MATCH_MAP = {
    "EXACT": MatchType.EXACT,
    "PHRASE": MatchType.PHRASE,
    "BROAD": MatchType.BROAD,
}


@dataclass(slots=True)
class GoogleAdsConfig:
    customer_id: str  # "1234567890" without dashes
    credentials_file: str | None = None  # path to google-ads.yaml
    credentials: dict[str, str] = field(default_factory=dict)
    login_customer_id: str | None = None  # MCC id for manager accounts
    currency: str = "USD"
    api_version: str = "v18"


class GoogleAdsError(ConnectorError):
    def __init__(self, message: str):
        super().__init__(Platform.GOOGLE, message)


class GoogleAdsConnector:
    """Async facade around the google-ads client."""

    platform: Platform = Platform.GOOGLE

    def __init__(self, config: GoogleAdsConfig):
        self.config = config
        self.account_id = config.customer_id.replace("-", "")
        self.currency = config.currency
        self._client: GoogleAdsClient | None = None

    def _get_client(self) -> GoogleAdsClient:
        if self._client is not None:
            return self._client
        try:
            from google.ads.googleads.client import GoogleAdsClient
        except ImportError as e:
            raise GoogleAdsError(
                "google-ads is not installed. `pip install google-ads`."
            ) from e
        if self.config.credentials_file:
            self._client = GoogleAdsClient.load_from_storage(
                path=self.config.credentials_file, version=self.config.api_version
            )
        elif self.config.credentials:
            self._client = GoogleAdsClient.load_from_dict(
                self.config.credentials, version=self.config.api_version
            )
        else:
            self._client = GoogleAdsClient.load_from_env(version=self.config.api_version)
        return self._client

    async def _search(self, query: str) -> list[Any]:
        def _run() -> list[Any]:
            client = self._get_client()
            ga_service = client.get_service("GoogleAdsService")
            try:
                stream = ga_service.search_stream(
                    customer_id=self.account_id, query=query
                )
                rows: list[Any] = []
                for batch in stream:
                    rows.extend(batch.results)
                return rows
            except Exception as e:  # GoogleAdsException etc.
                raise GoogleAdsError(f"GAQL failed: {e}") from e

        return await asyncio.to_thread(_run)

    @staticmethod
    def _date_clause(period: DateRange) -> str:
        return (
            f"segments.date BETWEEN '{period.start.isoformat()}' "
            f"AND '{period.end.isoformat()}'"
        )

    # ---------------- Interface implementation ----------------

    async def get_campaigns(self, period: DateRange) -> list[CampaignData]:
        query = f"""
            SELECT
              campaign.id,
              campaign.name,
              campaign.status,
              campaign.bidding_strategy_type,
              campaign_budget.amount_micros,
              metrics.impressions,
              metrics.clicks,
              metrics.cost_micros,
              metrics.conversions,
              metrics.conversions_value
            FROM campaign
            WHERE {self._date_clause(period)}
              AND campaign.status != 'REMOVED'
        """
        rows = await self._search(query)
        out: dict[str, CampaignData] = {}
        for row in rows:
            cid = str(row.campaign.id)
            if cid not in out:
                out[cid] = CampaignData(
                    platform=Platform.GOOGLE,
                    id=cid,
                    name=row.campaign.name,
                    status=_STATUS_MAP.get(
                        row.campaign.status.name, CampaignStatus.UNKNOWN
                    ),
                    daily_budget_minor=(
                        int(row.campaign_budget.amount_micros)
                        if row.campaign_budget.amount_micros
                        else None
                    ),
                    bidding_strategy=row.campaign.bidding_strategy_type.name,
                    metrics=Metrics(),
                    currency=self.currency,
                )
            m = out[cid].metrics
            m.impressions += int(row.metrics.impressions)
            m.clicks += int(row.metrics.clicks)
            m.cost_minor += int(row.metrics.cost_micros)
            m.conversions += float(row.metrics.conversions)
            m.conversion_value_minor += int(row.metrics.conversions_value * 1_000_000)
        return list(out.values())

    async def get_adgroups(
        self, campaign_ids: list[str] | None, period: DateRange
    ) -> list[AdGroupData]:
        filt = ""
        if campaign_ids:
            ids = ", ".join(campaign_ids)
            filt = f"AND campaign.id IN ({ids})"
        query = f"""
            SELECT
              ad_group.id,
              ad_group.name,
              ad_group.status,
              campaign.id,
              metrics.impressions,
              metrics.clicks,
              metrics.cost_micros,
              metrics.conversions
            FROM ad_group
            WHERE {self._date_clause(period)}
              AND ad_group.status != 'REMOVED'
              {filt}
        """
        rows = await self._search(query)
        out: dict[str, AdGroupData] = {}
        for row in rows:
            aid = str(row.ad_group.id)
            if aid not in out:
                out[aid] = AdGroupData(
                    platform=Platform.GOOGLE,
                    id=aid,
                    campaign_id=str(row.campaign.id),
                    name=row.ad_group.name,
                    status=_STATUS_MAP.get(
                        row.ad_group.status.name, CampaignStatus.UNKNOWN
                    ),
                    metrics=Metrics(),
                )
            m = out[aid].metrics
            m.impressions += int(row.metrics.impressions)
            m.clicks += int(row.metrics.clicks)
            m.cost_minor += int(row.metrics.cost_micros)
            m.conversions += float(row.metrics.conversions)
        return list(out.values())

    async def get_search_queries(
        self, period: DateRange, min_impressions: int = 1
    ) -> list[SearchQueryData]:
        query = f"""
            SELECT
              search_term_view.search_term,
              campaign.id,
              campaign.name,
              ad_group.id,
              ad_group.name,
              metrics.impressions,
              metrics.clicks,
              metrics.cost_micros,
              metrics.conversions
            FROM search_term_view
            WHERE {self._date_clause(period)}
              AND metrics.impressions >= {int(min_impressions)}
        """
        rows = await self._search(query)
        queries: list[SearchQueryData] = []
        for row in rows:
            queries.append(
                SearchQueryData(
                    platform=Platform.GOOGLE,
                    query=row.search_term_view.search_term,
                    campaign_id=str(row.campaign.id),
                    campaign_name=row.campaign.name,
                    adgroup_id=str(row.ad_group.id),
                    adgroup_name=row.ad_group.name,
                    metrics=Metrics(
                        impressions=int(row.metrics.impressions),
                        clicks=int(row.metrics.clicks),
                        cost_minor=int(row.metrics.cost_micros),
                        conversions=float(row.metrics.conversions),
                    ),
                )
            )
        return queries

    async def get_conversions(self, period: DateRange) -> list[ConversionData]:
        query = f"""
            SELECT
              campaign.id,
              ad_group.id,
              segments.conversion_action_name,
              metrics.conversions,
              metrics.conversions_value
            FROM ad_group
            WHERE {self._date_clause(period)}
        """
        rows = await self._search(query)
        out: list[ConversionData] = []
        for row in rows:
            out.append(
                ConversionData(
                    platform=Platform.GOOGLE,
                    campaign_id=str(row.campaign.id),
                    adgroup_id=str(row.ad_group.id),
                    conversion_name=row.segments.conversion_action_name,
                    count=float(row.metrics.conversions),
                    value_minor=int(row.metrics.conversions_value * 1_000_000),
                )
            )
        return out

    async def get_campaign_structure(self) -> CampaignTree:
        campaigns_q = """
            SELECT
              campaign.id,
              campaign.name,
              campaign.status,
              campaign.bidding_strategy_type,
              campaign_budget.amount_micros
            FROM campaign
            WHERE campaign.status != 'REMOVED'
        """
        rows = await self._search(campaigns_q)
        tree = CampaignTree(
            platform=Platform.GOOGLE,
            account_id=self.account_id,
            currency=self.currency,
        )
        campaigns: dict[str, CampaignNode] = {}
        for row in rows:
            cid = str(row.campaign.id)
            if cid in campaigns:
                continue
            campaigns[cid] = CampaignNode(
                id=cid,
                name=row.campaign.name,
                status=_STATUS_MAP.get(row.campaign.status.name, CampaignStatus.UNKNOWN),
                daily_budget_minor=(
                    int(row.campaign_budget.amount_micros)
                    if row.campaign_budget.amount_micros
                    else None
                ),
                bidding_strategy=row.campaign.bidding_strategy_type.name,
            )
        tree.campaigns = list(campaigns.values())

        adgroups_q = """
            SELECT
              ad_group.id,
              ad_group.name,
              ad_group.status,
              campaign.id
            FROM ad_group
            WHERE ad_group.status != 'REMOVED'
        """
        adgroup_rows = await self._search(adgroups_q)
        adgroup_map: dict[str, AdGroupNode] = {}
        for row in adgroup_rows:
            aid = str(row.ad_group.id)
            if aid in adgroup_map:
                continue
            node = AdGroupNode(
                id=aid,
                name=row.ad_group.name,
                status=_STATUS_MAP.get(
                    row.ad_group.status.name, CampaignStatus.UNKNOWN
                ),
            )
            adgroup_map[aid] = node
            cid = str(row.campaign.id)
            if cid in campaigns:
                campaigns[cid].adgroups.append(node)

        keywords_q = """
            SELECT
              ad_group_criterion.keyword.text,
              ad_group_criterion.keyword.match_type,
              ad_group_criterion.status,
              ad_group_criterion.quality_info.quality_score,
              ad_group.id
            FROM keyword_view
            WHERE ad_group_criterion.status != 'REMOVED'
              AND ad_group.status != 'REMOVED'
        """
        kw_rows = await self._search(keywords_q)
        for row in kw_rows:
            ag = adgroup_map.get(str(row.ad_group.id))
            if ag is None:
                continue
            ag.keywords.append(
                KeywordNode(
                    text=row.ad_group_criterion.keyword.text,
                    match_type=_MATCH_MAP.get(
                        row.ad_group_criterion.keyword.match_type.name,
                        MatchType.BROAD,
                    ),
                    quality_score=(
                        int(row.ad_group_criterion.quality_info.quality_score)
                        if row.ad_group_criterion.quality_info.quality_score
                        else None
                    ),
                    status=_STATUS_MAP.get(
                        row.ad_group_criterion.status.name, CampaignStatus.UNKNOWN
                    ),
                )
            )

        ads_count_q = """
            SELECT ad_group.id, metrics.impressions
            FROM ad_group_ad
            WHERE ad_group_ad.status != 'REMOVED'
        """
        ads_rows = await self._search(ads_count_q)
        ads_tally: dict[str, int] = {}
        for row in ads_rows:
            aid = str(row.ad_group.id)
            ads_tally[aid] = ads_tally.get(aid, 0) + 1
        for aid, count in ads_tally.items():
            if aid in adgroup_map:
                adgroup_map[aid].ads_count = count
        return tree

    async def add_negative_keywords(
        self, items: list[NegativeKeyword], dry_run: bool = True
    ) -> list[MutateResult]:
        if dry_run:
            return [
                MutateResult(success=True, resource_name=f"dry-run:{n.text}")
                for n in items
            ]

        def _apply() -> list[MutateResult]:
            client = self._get_client()
            results: list[MutateResult] = []
            campaign_svc = client.get_service("CampaignCriterionService")
            adgroup_svc = client.get_service("AdGroupCriterionService")
            match_enum = client.enums.KeywordMatchTypeEnum

            campaign_ops = []
            adgroup_ops = []

            for n in items:
                mt = {
                    MatchType.EXACT: match_enum.EXACT,
                    MatchType.PHRASE: match_enum.PHRASE,
                    MatchType.BROAD: match_enum.BROAD,
                }[n.match_type]
                if n.level == "campaign" and n.campaign_id:
                    op = client.get_type("CampaignCriterionOperation")
                    crit = op.create
                    crit.campaign = campaign_svc.campaign_path(
                        self.account_id, n.campaign_id
                    )
                    crit.negative = True
                    crit.keyword.text = n.text
                    crit.keyword.match_type = mt
                    campaign_ops.append(op)
                elif n.level == "adgroup" and n.adgroup_id:
                    op = client.get_type("AdGroupCriterionOperation")
                    crit = op.create
                    crit.ad_group = adgroup_svc.ad_group_path(
                        self.account_id, n.adgroup_id
                    )
                    crit.negative = True
                    crit.keyword.text = n.text
                    crit.keyword.match_type = mt
                    adgroup_ops.append(op)
                else:
                    results.append(
                        MutateResult(
                            success=False,
                            error=f"unsupported level={n.level} for Google Ads",
                        )
                    )

            if campaign_ops:
                try:
                    resp = campaign_svc.mutate_campaign_criteria(
                        customer_id=self.account_id, operations=campaign_ops
                    )
                    results.extend(
                        MutateResult(success=True, resource_name=r.resource_name)
                        for r in resp.results
                    )
                except Exception as e:
                    results.extend(
                        MutateResult(success=False, error=str(e)) for _ in campaign_ops
                    )
            if adgroup_ops:
                try:
                    resp = adgroup_svc.mutate_ad_group_criteria(
                        customer_id=self.account_id, operations=adgroup_ops
                    )
                    results.extend(
                        MutateResult(success=True, resource_name=r.resource_name)
                        for r in resp.results
                    )
                except Exception as e:
                    results.extend(
                        MutateResult(success=False, error=str(e)) for _ in adgroup_ops
                    )
            return results

        return await asyncio.to_thread(_apply)

    async def close(self) -> None:
        # google-ads client has no explicit close
        self._client = None
