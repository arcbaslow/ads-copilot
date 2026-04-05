"""Cross-platform data models.

All monetary values are stored as integers in the platform's minor currency unit
(micros for Google Ads, kopecks/tiyns for Yandex Direct). Conversion to major
units happens only at the presentation layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum


class Platform(str, Enum):
    GOOGLE = "google"
    YANDEX = "yandex"


class CampaignStatus(str, Enum):
    ENABLED = "enabled"
    PAUSED = "paused"
    REMOVED = "removed"
    UNKNOWN = "unknown"


class MatchType(str, Enum):
    EXACT = "exact"
    PHRASE = "phrase"
    BROAD = "broad"


@dataclass(frozen=True, slots=True)
class DateRange:
    start: date
    end: date

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise ValueError(f"start {self.start} is after end {self.end}")


@dataclass(slots=True)
class Metrics:
    """Performance metrics for a date range. Cost is in minor currency units."""

    impressions: int = 0
    clicks: int = 0
    cost_minor: int = 0
    conversions: float = 0.0
    conversion_value_minor: int = 0

    @property
    def ctr(self) -> float:
        return self.clicks / self.impressions if self.impressions else 0.0

    @property
    def cpc_minor(self) -> float:
        return self.cost_minor / self.clicks if self.clicks else 0.0

    @property
    def cpa_minor(self) -> float:
        return self.cost_minor / self.conversions if self.conversions else 0.0

    @property
    def roas(self) -> float:
        return (
            self.conversion_value_minor / self.cost_minor if self.cost_minor else 0.0
        )


@dataclass(slots=True)
class CampaignData:
    platform: Platform
    id: str
    name: str
    status: CampaignStatus
    daily_budget_minor: int | None
    bidding_strategy: str | None
    metrics: Metrics
    currency: str


@dataclass(slots=True)
class AdGroupData:
    platform: Platform
    id: str
    campaign_id: str
    name: str
    status: CampaignStatus
    metrics: Metrics


@dataclass(slots=True)
class SearchQueryData:
    platform: Platform
    query: str
    campaign_id: str
    campaign_name: str
    adgroup_id: str
    adgroup_name: str
    metrics: Metrics


@dataclass(slots=True)
class ConversionData:
    platform: Platform
    campaign_id: str
    adgroup_id: str | None
    conversion_name: str
    count: float
    value_minor: int


@dataclass(slots=True)
class KeywordNode:
    text: str
    match_type: MatchType
    quality_score: int | None = None
    cpc_minor: int | None = None
    status: CampaignStatus = CampaignStatus.ENABLED


@dataclass(slots=True)
class AdGroupNode:
    id: str
    name: str
    status: CampaignStatus
    keywords: list[KeywordNode] = field(default_factory=list)
    ads_count: int = 0


@dataclass(slots=True)
class CampaignNode:
    id: str
    name: str
    status: CampaignStatus
    daily_budget_minor: int | None
    bidding_strategy: str | None
    adgroups: list[AdGroupNode] = field(default_factory=list)


@dataclass(slots=True)
class CampaignTree:
    platform: Platform
    account_id: str
    currency: str
    campaigns: list[CampaignNode] = field(default_factory=list)


@dataclass(slots=True)
class NegativeKeyword:
    text: str
    match_type: MatchType
    level: str  # "account" | "campaign" | "adgroup"
    campaign_id: str | None = None
    adgroup_id: str | None = None
    reason: str | None = None


@dataclass(slots=True)
class MutateResult:
    success: bool
    resource_name: str | None = None
    error: str | None = None
