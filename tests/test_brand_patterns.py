from ads_copilot.analyzers.negative_finder import RuleBasedQueryFilter
from ads_copilot.models import Metrics, Platform, SearchQueryData


def _q(query: str, imp: int = 50, clk: int = 3, cost: int = 5_000_000) -> SearchQueryData:
    return SearchQueryData(
        platform=Platform.GOOGLE, query=query,
        campaign_id="c1", campaign_name="c", adgroup_id="a1", adgroup_name="a",
        metrics=Metrics(impressions=imp, clicks=clk, cost_minor=cost),
    )


def test_own_brand_never_negated() -> None:
    f = RuleBasedQueryFilter(
        brand_patterns=[r"\bgoodlabs\b"], min_impressions=5,
    )
    # This query ALSO matches the "reviews" rule, but brand wins
    out = f.classify([_q("goodlabs отзывы")])
    assert out == []


def test_competitor_pattern_categorized() -> None:
    f = RuleBasedQueryFilter(
        competitor_patterns=[r"\b(caspi|kaspi|halyk)\b"],
        min_impressions=5,
    )
    out = f.classify([_q("kaspi bank credit")])
    assert len(out) == 1
    assert out[0].category == "competitor"


def test_competitor_before_custom() -> None:
    # Both should match — competitor is layered in builtin-pattern spot, custom trails it
    f = RuleBasedQueryFilter(
        competitor_patterns=[r"\bkaspi\b"],
        custom_patterns=[r"\bbank\b"],
        min_impressions=5,
    )
    out = f.classify([_q("kaspi bank online")])
    assert out[0].category == "competitor"


def test_brand_overrides_competitor() -> None:
    # Even if a query contains a competitor pattern, own brand wins
    f = RuleBasedQueryFilter(
        brand_patterns=[r"\bours\b"],
        competitor_patterns=[r"\btheirs\b"],
        min_impressions=5,
    )
    out = f.classify([_q("ours vs theirs comparison")])
    assert out == []


def test_empty_brand_list_is_noop() -> None:
    f = RuleBasedQueryFilter(min_impressions=5)
    # No brand patterns — the query still gets flagged as informational
    out = f.classify([_q("что такое вклад")])
    assert len(out) == 1
