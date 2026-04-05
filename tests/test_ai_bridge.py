from ads_copilot.ai.bridge import ai_to_suggestions
from ads_copilot.ai.query_intent import Classification, ClassifiedQuery, Confidence
from ads_copilot.models import MatchType, Metrics, Platform, SearchQueryData


def _cq(category: Classification, query: str = "foo") -> ClassifiedQuery:
    sq = SearchQueryData(
        platform=Platform.GOOGLE,
        query=query,
        campaign_id="c1",
        campaign_name="x",
        adgroup_id="ag1",
        adgroup_name="y",
        metrics=Metrics(impressions=100, clicks=4, cost_minor=5_000_000),
    )
    return ClassifiedQuery(
        query=sq, category=category, reason="test", confidence=Confidence.HIGH
    )


def test_negative_exact_becomes_exact_suggestion() -> None:
    out = ai_to_suggestions([_cq(Classification.NEGATIVE_EXACT, "скачать приложение")])
    assert len(out) == 1
    assert out[0].match_type == MatchType.EXACT
    assert out[0].source == "ai"
    assert "скачать приложение" == out[0].query
    assert out[0].reason.startswith("ai:")


def test_negative_phrase_becomes_phrase_suggestion() -> None:
    out = ai_to_suggestions([_cq(Classification.NEGATIVE_PHRASE)])
    assert out[0].match_type == MatchType.PHRASE


def test_relevant_filtered_out() -> None:
    assert ai_to_suggestions([_cq(Classification.RELEVANT)]) == []


def test_brand_and_review_filtered_out() -> None:
    assert ai_to_suggestions([_cq(Classification.BRAND)]) == []
    assert ai_to_suggestions([_cq(Classification.REVIEW)]) == []


def test_ai_category_prefixed() -> None:
    out = ai_to_suggestions([_cq(Classification.NEGATIVE_EXACT)])
    assert out[0].category == "ai_negative_exact"
    assert out[0].confidence == "HIGH"
