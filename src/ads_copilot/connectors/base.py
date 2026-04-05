"""Common connector protocol. Every ad-platform adapter implements this."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

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


@runtime_checkable
class AdPlatformConnector(Protocol):
    """Unified interface for Google Ads and Yandex Direct."""

    platform: Platform
    account_id: str
    currency: str

    async def get_campaigns(self, period: DateRange) -> list[CampaignData]: ...

    async def get_adgroups(
        self, campaign_ids: list[str] | None, period: DateRange
    ) -> list[AdGroupData]: ...

    async def get_search_queries(
        self, period: DateRange, min_impressions: int = 1
    ) -> list[SearchQueryData]: ...

    async def get_conversions(self, period: DateRange) -> list[ConversionData]: ...

    async def get_campaign_structure(self) -> CampaignTree: ...

    async def add_negative_keywords(
        self, items: list[NegativeKeyword], dry_run: bool = True
    ) -> list[MutateResult]: ...

    async def close(self) -> None: ...


class ConnectorError(Exception):
    """Base class for platform connector errors."""

    def __init__(self, platform: Platform, message: str, *, status_code: int | None = None):
        self.platform = platform
        self.status_code = status_code
        super().__init__(f"[{platform.value}] {message}")
