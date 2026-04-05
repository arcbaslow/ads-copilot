"""Yandex Direct API v5 async connector.

Uses httpx directly against the JSON endpoint. Handles report polling
(201/202 -> retry-in header -> retry) and agency accounts via Client-Login.

Reference:
    https://yandex.com/dev/direct/doc/dg/concepts/about-en.html
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from ads_copilot.connectors.base import ConnectorError
from ads_copilot.connectors.retry import RetryPolicy, retry_http
from ads_copilot.models import (
    AdGroupData,
    CampaignData,
    CampaignNode,
    CampaignStatus,
    CampaignTree,
    ConversionData,
    DateRange,
    Metrics,
    MutateResult,
    NegativeKeyword,
    Platform,
    SearchQueryData,
)

log = logging.getLogger(__name__)

API_BASE = "https://api.direct.yandex.com/json/v5"
SANDBOX_BASE = "https://api-sandbox.direct.yandex.com/json/v5"

# Yandex returns currency in a separate call. We cache a map from
# 3-letter code to minor-unit multiplier.
MINOR_UNITS = {
    "RUB": 1_000_000,  # Yandex returns cost in micros (RUB * 10^6)
    "KZT": 1_000_000,
    "BYN": 1_000_000,
    "USD": 1_000_000,
    "EUR": 1_000_000,
    "CHF": 1_000_000,
    "TRY": 1_000_000,
    "UAH": 1_000_000,
    "UZS": 1_000_000,
}


_STATUS_MAP = {
    "ON": CampaignStatus.ENABLED,
    "SUSPENDED": CampaignStatus.PAUSED,
    "OFF": CampaignStatus.PAUSED,
    "ARCHIVED": CampaignStatus.REMOVED,
    "ENDED": CampaignStatus.REMOVED,
    "CONVERTING": CampaignStatus.ENABLED,
    "ACCEPTED": CampaignStatus.ENABLED,
    "DRAFT": CampaignStatus.PAUSED,
    "MODERATION": CampaignStatus.PAUSED,
    "REJECTED": CampaignStatus.PAUSED,
}


def _map_status(raw: str | None) -> CampaignStatus:
    if raw is None:
        return CampaignStatus.UNKNOWN
    return _STATUS_MAP.get(raw.upper(), CampaignStatus.UNKNOWN)


@dataclass(slots=True)
class YandexConfig:
    token: str
    login: str
    client_login: str | None = None  # for agency accounts
    sandbox: bool = False
    currency: str = "RUB"
    language: str = "ru"
    request_timeout: float = 60.0
    report_poll_interval_cap: float = 30.0
    report_max_attempts: int = 60
    retry_max_attempts: int = 4
    retry_base_delay: float = 1.0


class YandexDirectError(ConnectorError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(Platform.YANDEX, message, status_code=status_code)


class YandexDirectConnector:
    """Async connector for Yandex Direct API v5."""

    platform: Platform = Platform.YANDEX

    def __init__(self, config: YandexConfig, client: httpx.AsyncClient | None = None):
        self.config = config
        self.account_id = config.client_login or config.login
        self.currency = config.currency
        self._base = SANDBOX_BASE if config.sandbox else API_BASE
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=config.request_timeout)
        self._retry_policy = RetryPolicy(
            max_attempts=config.retry_max_attempts,
            base_delay=config.retry_base_delay,
        )

    @property
    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.config.token}",
            "Accept-Language": self.config.language,
            "Content-Type": "application/json; charset=utf-8",
        }
        if self.config.client_login:
            headers["Client-Login"] = self.config.client_login
        return headers

    @property
    def _report_headers(self) -> dict[str, str]:
        return {
            **self._headers,
            "processingMode": "auto",
            "returnMoneyInMicros": "true",
            "skipReportHeader": "true",
            "skipColumnHeader": "false",
            "skipReportSummary": "true",
        }

    async def _call(self, service: str, method: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base}/{service}"
        body = {"method": method, "params": params}
        resp = await retry_http(
            lambda: self._client.post(url, json=body, headers=self._headers),
            policy=self._retry_policy,
            description=f"yandex {service}.{method}",
        )
        if resp.status_code != 200:
            raise YandexDirectError(
                f"{service}.{method} returned HTTP {resp.status_code}: {resp.text}",
                status_code=resp.status_code,
            )
        data = resp.json()
        if "error" in data:
            err = data["error"]
            raise YandexDirectError(
                f"{service}.{method}: {err.get('error_string')} - {err.get('error_detail')}",
                status_code=err.get("error_code"),
            )
        return data.get("result", {})

    def _minor_unit_factor(self) -> int:
        return MINOR_UNITS.get(self.currency.upper(), 1_000_000)

    async def _fetch_report(self, report_body: dict[str, Any]) -> list[dict[str, str]]:
        """Poll Yandex's async report endpoint until ready, return parsed TSV rows."""
        url = f"{self._base}/reports"
        attempts = 0
        while attempts < self.config.report_max_attempts:
            resp = await retry_http(
                lambda: self._client.post(
                    url, json=report_body, headers=self._report_headers,
                ),
                policy=self._retry_policy,
                description="yandex reports",
            )
            if resp.status_code == 200:
                return _parse_tsv(resp.text)
            if resp.status_code in (201, 202):
                retry_in = min(
                    float(resp.headers.get("retryIn", 5)),
                    self.config.report_poll_interval_cap,
                )
                log.debug("Yandex report not ready, retry in %.1fs", retry_in)
                await asyncio.sleep(retry_in)
                attempts += 1
                continue
            raise YandexDirectError(
                f"reports endpoint returned HTTP {resp.status_code}: {resp.text}",
                status_code=resp.status_code,
            )
        raise YandexDirectError(
            f"report polling exceeded {self.config.report_max_attempts} attempts"
        )

    # ---------------- Interface implementation ----------------

    async def get_campaigns(self, period: DateRange) -> list[CampaignData]:
        performance = await self._get_campaign_performance(period)

        get_result = await self._call(
            "campaigns",
            "get",
            {
                "SelectionCriteria": {},
                "FieldNames": [
                    "Id",
                    "Name",
                    "State",
                    "Status",
                    "DailyBudget",
                ],
            },
        )
        factor = self._minor_unit_factor()
        campaigns: list[CampaignData] = []
        for c in get_result.get("Campaigns", []):
            cid = str(c["Id"])
            daily_budget_minor: int | None = None
            if c.get("DailyBudget") and c["DailyBudget"].get("Amount") is not None:
                # DailyBudget.Amount is in micros already
                daily_budget_minor = int(c["DailyBudget"]["Amount"])
            metrics = performance.get(cid, Metrics())
            campaigns.append(
                CampaignData(
                    platform=Platform.YANDEX,
                    id=cid,
                    name=c.get("Name", ""),
                    status=_map_status(c.get("State") or c.get("Status")),
                    daily_budget_minor=daily_budget_minor,
                    bidding_strategy=None,
                    metrics=metrics,
                    currency=self.currency,
                )
            )
        _ = factor  # silence unused
        return campaigns

    async def _get_campaign_performance(self, period: DateRange) -> dict[str, Metrics]:
        body = {
            "params": {
                "SelectionCriteria": {
                    "DateFrom": period.start.isoformat(),
                    "DateTo": period.end.isoformat(),
                },
                "FieldNames": [
                    "CampaignId",
                    "Impressions",
                    "Clicks",
                    "Cost",
                    "Conversions",
                ],
                "ReportName": f"Campaigns_{period.start.isoformat()}_{period.end.isoformat()}",
                "ReportType": "CAMPAIGN_PERFORMANCE_REPORT",
                "DateRangeType": "CUSTOM_DATE",
                "Format": "TSV",
                "IncludeVAT": "YES",
                "IncludeDiscount": "NO",
            },
        }
        rows = await self._fetch_report(body)
        out: dict[str, Metrics] = {}
        for row in rows:
            cid = row["CampaignId"]
            m = out.setdefault(cid, Metrics())
            m.impressions += _int(row.get("Impressions"))
            m.clicks += _int(row.get("Clicks"))
            m.cost_minor += _int(row.get("Cost"))
            m.conversions += _float(row.get("Conversions"))
        return out

    async def get_adgroups(
        self, campaign_ids: list[str] | None, period: DateRange
    ) -> list[AdGroupData]:
        selection: dict[str, Any] = {}
        if campaign_ids:
            selection["CampaignIds"] = [int(c) for c in campaign_ids]
        result = await self._call(
            "adgroups",
            "get",
            {
                "SelectionCriteria": selection,
                "FieldNames": ["Id", "CampaignId", "Name", "Status"],
            },
        )
        # Fetch adgroup-level performance in a single report
        perf = await self._get_adgroup_performance(period, campaign_ids)
        adgroups: list[AdGroupData] = []
        for a in result.get("AdGroups", []):
            aid = str(a["Id"])
            adgroups.append(
                AdGroupData(
                    platform=Platform.YANDEX,
                    id=aid,
                    campaign_id=str(a["CampaignId"]),
                    name=a.get("Name", ""),
                    status=_map_status(a.get("Status")),
                    metrics=perf.get(aid, Metrics()),
                )
            )
        return adgroups

    async def _get_adgroup_performance(
        self, period: DateRange, campaign_ids: list[str] | None
    ) -> dict[str, Metrics]:
        selection: dict[str, Any] = {
            "DateFrom": period.start.isoformat(),
            "DateTo": period.end.isoformat(),
        }
        if campaign_ids:
            selection["Filter"] = [
                {"Field": "CampaignId", "Operator": "IN", "Values": campaign_ids}
            ]
        body = {
            "params": {
                "SelectionCriteria": selection,
                "FieldNames": [
                    "AdGroupId",
                    "Impressions",
                    "Clicks",
                    "Cost",
                    "Conversions",
                ],
                "ReportName": f"AdGroups_{period.start.isoformat()}_{period.end.isoformat()}",
                "ReportType": "ADGROUP_PERFORMANCE_REPORT",
                "DateRangeType": "CUSTOM_DATE",
                "Format": "TSV",
                "IncludeVAT": "YES",
                "IncludeDiscount": "NO",
            },
        }
        rows = await self._fetch_report(body)
        out: dict[str, Metrics] = {}
        for row in rows:
            aid = row["AdGroupId"]
            m = out.setdefault(aid, Metrics())
            m.impressions += _int(row.get("Impressions"))
            m.clicks += _int(row.get("Clicks"))
            m.cost_minor += _int(row.get("Cost"))
            m.conversions += _float(row.get("Conversions"))
        return out

    async def get_search_queries(
        self, period: DateRange, min_impressions: int = 1
    ) -> list[SearchQueryData]:
        body = {
            "params": {
                "SelectionCriteria": {
                    "DateFrom": period.start.isoformat(),
                    "DateTo": period.end.isoformat(),
                    "Filter": [
                        {
                            "Field": "Impressions",
                            "Operator": "GREATER_OR_EQUAL",
                            "Values": [str(min_impressions)],
                        }
                    ],
                },
                "FieldNames": [
                    "Query",
                    "CampaignId",
                    "CampaignName",
                    "AdGroupId",
                    "AdGroupName",
                    "Impressions",
                    "Clicks",
                    "Cost",
                    "Conversions",
                ],
                "ReportName": f"SearchQueries_{period.start.isoformat()}_{period.end.isoformat()}",
                "ReportType": "SEARCH_QUERY_PERFORMANCE_REPORT",
                "DateRangeType": "CUSTOM_DATE",
                "Format": "TSV",
                "IncludeVAT": "YES",
                "IncludeDiscount": "NO",
            },
        }
        rows = await self._fetch_report(body)
        queries: list[SearchQueryData] = []
        for row in rows:
            queries.append(
                SearchQueryData(
                    platform=Platform.YANDEX,
                    query=row.get("Query", ""),
                    campaign_id=row.get("CampaignId", ""),
                    campaign_name=row.get("CampaignName", ""),
                    adgroup_id=row.get("AdGroupId", ""),
                    adgroup_name=row.get("AdGroupName", ""),
                    metrics=Metrics(
                        impressions=_int(row.get("Impressions")),
                        clicks=_int(row.get("Clicks")),
                        cost_minor=_int(row.get("Cost")),
                        conversions=_float(row.get("Conversions")),
                    ),
                )
            )
        return queries

    async def get_conversions(self, period: DateRange) -> list[ConversionData]:
        # Yandex exposes Goal-level conversions via CUSTOM_REPORT with GoalId.
        body = {
            "params": {
                "SelectionCriteria": {
                    "DateFrom": period.start.isoformat(),
                    "DateTo": period.end.isoformat(),
                },
                "FieldNames": [
                    "CampaignId",
                    "AdGroupId",
                    "GoalsRoi",
                    "Conversions",
                    "ConversionRate",
                    "Cost",
                ],
                "ReportName": f"Conversions_{period.start.isoformat()}_{period.end.isoformat()}",
                "ReportType": "CUSTOM_REPORT",
                "DateRangeType": "CUSTOM_DATE",
                "Format": "TSV",
                "IncludeVAT": "YES",
                "IncludeDiscount": "NO",
            },
        }
        rows = await self._fetch_report(body)
        out: list[ConversionData] = []
        for row in rows:
            out.append(
                ConversionData(
                    platform=Platform.YANDEX,
                    campaign_id=row.get("CampaignId", ""),
                    adgroup_id=row.get("AdGroupId") or None,
                    conversion_name="default",
                    count=_float(row.get("Conversions")),
                    value_minor=0,
                )
            )
        return out

    async def get_campaign_structure(self) -> CampaignTree:
        campaigns_result = await self._call(
            "campaigns",
            "get",
            {
                "SelectionCriteria": {},
                "FieldNames": [
                    "Id",
                    "Name",
                    "State",
                    "Status",
                    "DailyBudget",
                ],
            },
        )
        tree = CampaignTree(
            platform=Platform.YANDEX,
            account_id=self.account_id,
            currency=self.currency,
        )
        campaign_ids: list[int] = []
        for c in campaigns_result.get("Campaigns", []):
            daily_budget_minor = None
            if c.get("DailyBudget") and c["DailyBudget"].get("Amount") is not None:
                daily_budget_minor = int(c["DailyBudget"]["Amount"])
            tree.campaigns.append(
                CampaignNode(
                    id=str(c["Id"]),
                    name=c.get("Name", ""),
                    status=_map_status(c.get("State") or c.get("Status")),
                    daily_budget_minor=daily_budget_minor,
                    bidding_strategy=None,
                )
            )
            campaign_ids.append(int(c["Id"]))

        if not campaign_ids:
            return tree

        adgroups_result = await self._call(
            "adgroups",
            "get",
            {
                "SelectionCriteria": {"CampaignIds": campaign_ids},
                "FieldNames": ["Id", "CampaignId", "Name", "Status"],
            },
        )
        by_campaign: dict[str, list[dict[str, Any]]] = {}
        for a in adgroups_result.get("AdGroups", []):
            by_campaign.setdefault(str(a["CampaignId"]), []).append(a)

        for campaign in tree.campaigns:
            from ads_copilot.models import AdGroupNode

            for a in by_campaign.get(campaign.id, []):
                campaign.adgroups.append(
                    AdGroupNode(
                        id=str(a["Id"]),
                        name=a.get("Name", ""),
                        status=_map_status(a.get("Status")),
                    )
                )
        return tree

    async def add_negative_keywords(
        self, items: list[NegativeKeyword], dry_run: bool = True
    ) -> list[MutateResult]:
        if dry_run:
            return [
                MutateResult(success=True, resource_name=f"dry-run:{n.text}")
                for n in items
            ]
        # Group by scope. Yandex applies negatives per campaign or adgroup.
        results: list[MutateResult] = []
        by_campaign: dict[str, list[str]] = {}
        by_adgroup: dict[str, list[str]] = {}
        for n in items:
            if n.level == "campaign" and n.campaign_id:
                by_campaign.setdefault(n.campaign_id, []).append(n.text)
            elif n.level == "adgroup" and n.adgroup_id:
                by_adgroup.setdefault(n.adgroup_id, []).append(n.text)
            else:
                results.append(
                    MutateResult(
                        success=False,
                        error=f"Yandex negatives need campaign_id or adgroup_id (got level={n.level})",
                    )
                )

        for cid, words in by_campaign.items():
            try:
                await self._call(
                    "campaigns",
                    "update",
                    {
                        "Campaigns": [
                            {
                                "Id": int(cid),
                                "NegativeKeywords": {"Items": words},
                            }
                        ]
                    },
                )
                results.extend(
                    MutateResult(success=True, resource_name=f"campaign:{cid}:{w}")
                    for w in words
                )
            except YandexDirectError as e:
                results.extend(
                    MutateResult(success=False, error=str(e)) for _ in words
                )

        for aid, words in by_adgroup.items():
            try:
                await self._call(
                    "adgroups",
                    "update",
                    {
                        "AdGroups": [
                            {
                                "Id": int(aid),
                                "NegativeKeywords": {"Items": words},
                            }
                        ]
                    },
                )
                results.extend(
                    MutateResult(success=True, resource_name=f"adgroup:{aid}:{w}")
                    for w in words
                )
            except YandexDirectError as e:
                results.extend(
                    MutateResult(success=False, error=str(e)) for _ in words
                )
        return results

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> YandexDirectConnector:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()


# ---------------- helpers ----------------


def _parse_tsv(text: str) -> list[dict[str, str]]:
    """Parse Yandex TSV report. First line is the header row."""
    # Strip potential BOM
    if text.startswith("\ufeff"):
        text = text[1:]
    text = text.strip()
    if not text:
        return []
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    return [dict(r) for r in reader]


def _int(value: str | None) -> int:
    if value is None or value == "" or value == "--":
        return 0
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return 0


def _float(value: str | None) -> float:
    if value is None or value == "" or value == "--":
        return 0.0
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


