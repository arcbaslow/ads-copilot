from ads_copilot.analyzers.negative_finder import RuleBasedQueryFilter
from ads_copilot.models import Metrics, Platform, SearchQueryData


def _q(query: str, imp: int = 50, clk: int = 3, cost: int = 5_000_000, conv: float = 0.0) -> SearchQueryData:
    return SearchQueryData(
        platform=Platform.GOOGLE,
        query=query,
        campaign_id="c1",
        campaign_name="camp",
        adgroup_id="ag1",
        adgroup_name="ag",
        metrics=Metrics(impressions=imp, clicks=clk, cost_minor=cost, conversions=conv),
    )


def test_flags_russian_informational() -> None:
    f = RuleBasedQueryFilter(min_impressions=5)
    out = f.classify([_q("что такое ипотека")])
    assert len(out) == 1
    assert "informational_ru" in out[0].reason


def test_flags_english_job_seeker() -> None:
    f = RuleBasedQueryFilter(min_impressions=5)
    out = f.classify([_q("bank teller salary almaty")])
    assert len(out) == 1
    assert "job_seekers" in out[0].reason


def test_ignores_converted_queries() -> None:
    f = RuleBasedQueryFilter(min_impressions=5)
    out = f.classify([_q("как получить кредит", conv=2.0)])
    assert out == []


def test_ignores_low_impression_queries() -> None:
    f = RuleBasedQueryFilter(min_impressions=10)
    out = f.classify([_q("how to apply for loan", imp=3)])
    assert out == []


def test_custom_patterns_work() -> None:
    f = RuleBasedQueryFilter(
        custom_patterns=[r"\b(каспий|халык)\b"], min_impressions=5
    )
    out = f.classify([_q("халык банк кредит")])
    assert len(out) == 1
    assert out[0].category == "custom"


def test_sorts_by_cost_descending() -> None:
    f = RuleBasedQueryFilter(min_impressions=5)
    out = f.classify(
        [
            _q("скачать мобильный банкинг", cost=1_000_000),
            _q("отзывы о банке", cost=10_000_000),
            _q("что такое депозит", cost=5_000_000),
        ]
    )
    assert [s.cost_minor for s in out] == [10_000_000, 5_000_000, 1_000_000]


def test_exact_match_when_high_clicks() -> None:
    from ads_copilot.models import MatchType

    f = RuleBasedQueryFilter(min_impressions=5)
    out = f.classify([_q("халык вакансии astana", clk=5)])
    assert out[0].match_type == MatchType.EXACT

    out2 = f.classify([_q("халык вакансии astana", clk=1)])
    assert out2[0].match_type == MatchType.PHRASE
