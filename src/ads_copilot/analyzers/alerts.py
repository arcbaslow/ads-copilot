"""Alert datamodel shared by analyzers."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ads_copilot.models import Platform


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return {"info": 0, "warning": 1, "critical": 2}[self.value]

    @property
    def icon(self) -> str:
        return {"info": "ℹ️", "warning": "⚠️", "critical": "🔴"}[self.value]


@dataclass(slots=True)
class Alert:
    """One actionable finding."""

    severity: Severity
    category: str  # "spend" | "performance" | "structure" | "queries" | "conversions"
    platform: Platform | None
    title: str
    detail: str
    campaign_id: str | None = None
    campaign_name: str | None = None
    metric_values: dict[str, Any] = field(default_factory=dict)

    def sort_key(self) -> tuple[int, str, str]:
        # Higher severity first, then category, then campaign name
        return (-self.severity.rank, self.category, self.campaign_name or "")
