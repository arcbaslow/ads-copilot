"""Fake in-memory connector used by MCP tool tests."""

from __future__ import annotations

from ads_copilot.connectors.base import AdPlatformConnector
from ads_copilot.models import (
    AdGroupData,
    CampaignData,
    CampaignTree,
    ConversionData,
    DateRange,
    MutateResult,
    NegativeKeyword,
    Platform,
    SearchQueryData,
)


class FakeConnector:
    """In-memory connector holding canned data. Satisfies AdPlatformConnector."""

    def __init__(
        self,
        platform: Platform,
        account_id: str = "test-account",
        currency: str = "USD",
        campaigns: list[CampaignData] | None = None,
        queries: list[SearchQueryData] | None = None,
        tree: CampaignTree | None = None,
    ):
        self.platform = platform
        self.account_id = account_id
        self.currency = currency
        self._campaigns = campaigns or []
        self._queries = queries or []
        self._tree = tree or CampaignTree(
            platform=platform, account_id=account_id, currency=currency
        )
        self.applied_negatives: list[tuple[list[NegativeKeyword], bool]] = []

    async def get_campaigns(self, period: DateRange) -> list[CampaignData]:
        return list(self._campaigns)

    async def get_adgroups(
        self, campaign_ids: list[str] | None, period: DateRange
    ) -> list[AdGroupData]:
        return []

    async def get_search_queries(
        self, period: DateRange, min_impressions: int = 1
    ) -> list[SearchQueryData]:
        return [q for q in self._queries if q.metrics.impressions >= min_impressions]

    async def get_conversions(self, period: DateRange) -> list[ConversionData]:
        return []

    async def get_campaign_structure(self) -> CampaignTree:
        return self._tree

    async def add_negative_keywords(
        self, items: list[NegativeKeyword], dry_run: bool = True
    ) -> list[MutateResult]:
        self.applied_negatives.append((items, dry_run))
        return [
            MutateResult(
                success=True,
                resource_name=f"{'dry' if dry_run else 'live'}:{n.text}",
            )
            for n in items
        ]

    async def close(self) -> None:
        pass


# sanity check: the protocol is satisfied
_: AdPlatformConnector = FakeConnector(Platform.GOOGLE)
del _
