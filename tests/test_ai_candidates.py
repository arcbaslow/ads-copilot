from ads_copilot.audit import _ai_candidates
from ads_copilot.models import Metrics, Platform, SearchQueryData


def _q(q: str, imp: int, clk: int, cost: int, conv: float = 0) -> SearchQueryData:
    return SearchQueryData(
        platform=Platform.GOOGLE,
        query=q,
        campaign_id="c1",
        campaign_name="x",
        adgroup_id="ag1",
        adgroup_name="y",
        metrics=Metrics(impressions=imp, clicks=clk, cost_minor=cost, conversions=conv),
    )


def test_excludes_rule_flagged() -> None:
    out = _ai_candidates(
        [_q("a", 100, 5, 1_000_000), _q("b", 100, 5, 1_000_000)],
        already_flagged={"a"},
        min_impressions=5,
    )
    assert [q.query for q in out] == ["b"]


def test_excludes_converted() -> None:
    out = _ai_candidates(
        [_q("converter", 100, 5, 1_000_000, conv=2)],
        already_flagged=set(),
        min_impressions=5,
    )
    assert out == []


def test_excludes_low_impressions() -> None:
    out = _ai_candidates(
        [_q("tiny", 3, 1, 100_000)],
        already_flagged=set(),
        min_impressions=5,
    )
    assert out == []


def test_excludes_zero_activity() -> None:
    out = _ai_candidates(
        [_q("noise", 100, 0, 0)],
        already_flagged=set(),
        min_impressions=5,
    )
    assert out == []


def test_ranks_by_cost_descending() -> None:
    out = _ai_candidates(
        [
            _q("cheap", 100, 2, 500_000),
            _q("expensive", 100, 5, 10_000_000),
            _q("medium", 100, 3, 3_000_000),
        ],
        already_flagged=set(),
        min_impressions=5,
    )
    assert [q.query for q in out] == ["expensive", "medium", "cheap"]


def test_caps_at_max() -> None:
    from ads_copilot.audit import MAX_AI_QUERIES_PER_ACCOUNT

    many = [_q(f"q{i}", 100, 1, i * 1000 + 1) for i in range(MAX_AI_QUERIES_PER_ACCOUNT + 50)]
    out = _ai_candidates(many, already_flagged=set(), min_impressions=5)
    assert len(out) == MAX_AI_QUERIES_PER_ACCOUNT
