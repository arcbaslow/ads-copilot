"""Rule-based negative keyword discovery.

Applies a stack of regex patterns (bilingual RU+EN) to search queries and
returns NegativeKeyword suggestions. The rule layer is cheap and runs before
the optional AI classifier.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ads_copilot.models import MatchType, NegativeKeyword, SearchQueryData

# Built-in patterns. Account-specific patterns are appended from config.
# Each entry is (category, regex_source) — compiled lazily below.
BUILTIN_PATTERNS: list[tuple[str, str]] = [
    # Informational (English): "how to", "what is"
    ("informational_en", r"\b(what|how|why|when|where|who|is|are|can|does|guide|tutorial|meaning|definition)\b"),
    # Informational (Russian)
    ("informational_ru", r"\b(что|как|почему|когда|где|кто|можно\s+ли|значение|определение|это)\b"),
    # Free / download intent
    ("free_download", r"\b(free|бесплатно|бесплатный|скачать|download|torrent|crack|взлом)\b"),
    # Reviews / social proof browsing
    ("reviews_social", r"\b(отзывы|отзыв|review|reviews|reddit|youtube|video|видео|форум|forum)\b"),
    # Job seekers
    ("job_seekers", r"\b(вакансии|вакансия|работа|job|career|salary|зарплата|resume|резюме)\b"),
    # DIY / self-help competing with paid products
    ("diy", r"\b(своими\s+руками|diy|самостоятельно|без\s+посредников)\b"),
    # Photo/wallpaper (common noise for brand keywords)
    ("images", r"\b(фото|картинка|картинки|обои|wallpaper|png|jpg|photo|image)\b"),
]


@dataclass(slots=True)
class Suggestion:
    query: str
    match_type: MatchType
    level: str  # "adgroup" | "campaign"
    campaign_id: str | None
    adgroup_id: str | None
    reason: str
    category: str
    cost_minor: int
    clicks: int
    conversions: float

    def to_negative(self) -> NegativeKeyword:
        return NegativeKeyword(
            text=self.query,
            match_type=self.match_type,
            level=self.level,
            campaign_id=self.campaign_id,
            adgroup_id=self.adgroup_id,
            reason=self.reason,
        )


class RuleBasedQueryFilter:
    """Classify search queries against regex patterns."""

    def __init__(
        self,
        custom_patterns: list[str] | None = None,
        min_impressions: int = 5,
    ) -> None:
        self.min_impressions = min_impressions
        self._patterns: list[tuple[str, re.Pattern[str]]] = [
            (cat, re.compile(src, re.IGNORECASE | re.UNICODE))
            for cat, src in BUILTIN_PATTERNS
        ]
        for p in custom_patterns or []:
            self._patterns.append(
                ("custom", re.compile(p, re.IGNORECASE | re.UNICODE))
            )

    def classify(self, queries: list[SearchQueryData]) -> list[Suggestion]:
        out: list[Suggestion] = []
        for q in queries:
            if q.metrics.impressions < self.min_impressions:
                continue
            if q.metrics.conversions > 0:
                # Don't negate queries that actually converted.
                continue
            category = self._first_match(q.query)
            if category is None:
                continue
            # Queries with high clicks are more confident candidates for exact match
            match_type = MatchType.EXACT if q.metrics.clicks >= 3 else MatchType.PHRASE
            out.append(
                Suggestion(
                    query=q.query,
                    match_type=match_type,
                    level="adgroup" if q.adgroup_id else "campaign",
                    campaign_id=q.campaign_id or None,
                    adgroup_id=q.adgroup_id or None,
                    reason=f"matches rule: {category}",
                    category=category,
                    cost_minor=q.metrics.cost_minor,
                    clicks=q.metrics.clicks,
                    conversions=q.metrics.conversions,
                )
            )
        # Highest-cost wasted spend first
        out.sort(key=lambda s: -s.cost_minor)
        return out

    def _first_match(self, text: str) -> str | None:
        for cat, pat in self._patterns:
            if pat.search(text):
                return cat
        return None
