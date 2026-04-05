"""Adapters that turn AI classifications into ready-to-use negative suggestions."""

from __future__ import annotations

from ads_copilot.ai.query_intent import Classification, ClassifiedQuery
from ads_copilot.analyzers.negative_finder import Suggestion
from ads_copilot.models import MatchType


def ai_to_suggestions(classified: list[ClassifiedQuery]) -> list[Suggestion]:
    """Convert AI NEGATIVE_* classifications into Suggestion objects.
    RELEVANT/BRAND/REVIEW are filtered out."""
    out: list[Suggestion] = []
    for c in classified:
        match_type = _match_for(c.category)
        if match_type is None:
            continue
        sq = c.query
        out.append(
            Suggestion(
                query=sq.query,
                match_type=match_type,
                level="adgroup" if sq.adgroup_id else "campaign",
                campaign_id=sq.campaign_id or None,
                adgroup_id=sq.adgroup_id or None,
                reason=f"ai: {c.reason}" if c.reason else "ai classification",
                category=f"ai_{c.category.value.lower()}",
                cost_minor=sq.metrics.cost_minor,
                clicks=sq.metrics.clicks,
                conversions=sq.metrics.conversions,
                source="ai",
                confidence=c.confidence.value,
            )
        )
    return out


def _match_for(category: Classification) -> MatchType | None:
    if category == Classification.NEGATIVE_EXACT:
        return MatchType.EXACT
    if category == Classification.NEGATIVE_PHRASE:
        return MatchType.PHRASE
    return None
