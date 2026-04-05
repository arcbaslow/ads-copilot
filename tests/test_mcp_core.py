from datetime import date

import pytest

from ads_copilot.config import Config, AccountsConfig, YandexDirectAccount, BusinessConfig
from ads_copilot.mcp import core
from ads_copilot.mcp.registry import StaticRegistry
from ads_copilot.models import (
    CampaignData,
    CampaignNode,
    CampaignStatus,
    CampaignTree,
    Metrics,
    Platform,
    SearchQueryData,
)
from tests.fakes import FakeConnector


def _cfg() -> Config:
    return Config(
        accounts=AccountsConfig(
            yandex_direct=[YandexDirectAccount(name="t", login="t", token_env="X")]
        ),
        business=BusinessConfig(type="fintech", currency="USD"),
    )


def _campaign(cid: str, cost: int, budget: int | None = 500_000_000, name: str | None = None) -> CampaignData:
    return CampaignData(
        platform=Platform.GOOGLE,
        id=cid,
        name=name or f"Campaign {cid}",
        status=CampaignStatus.ENABLED,
        daily_budget_minor=budget,
        bidding_strategy="TargetCPA",
        metrics=Metrics(impressions=1000, clicks=50, cost_minor=cost, conversions=5),
        currency="USD",
    )


def _query(q: str, cost: int = 5_000_000, conv: float = 0) -> SearchQueryData:
    return SearchQueryData(
        platform=Platform.GOOGLE,
        query=q,
        campaign_id="1",
        campaign_name="C1",
        adgroup_id="10",
        adgroup_name="AG",
        metrics=Metrics(impressions=100, clicks=4, cost_minor=cost, conversions=conv),
    )


def _registry(**conns) -> StaticRegistry:  # type: ignore[no-untyped-def]
    return StaticRegistry(conns)


# ---------------- parse_period ----------------


def test_parse_period_yesterday() -> None:
    from datetime import timedelta

    dr, label = core.parse_period("yesterday", None, None)
    assert label == "yesterday"
    assert dr.start == dr.end
    assert dr.end == date.today() - timedelta(days=1)


def test_parse_period_last_7_days() -> None:
    dr, label = core.parse_period("last_7_days", None, None)
    assert label == "last 7 days"
    assert (dr.end - dr.start).days == 7


def test_parse_period_custom_requires_dates() -> None:
    with pytest.raises(core.ToolError):
        core.parse_period("custom", None, None)


def test_parse_period_custom_ok() -> None:
    dr, label = core.parse_period("custom", "2026-01-01", "2026-01-31")
    assert dr.start.isoformat() == "2026-01-01"
    assert dr.end.isoformat() == "2026-01-31"
    assert "2026-01-01" in label


def test_parse_period_invalid() -> None:
    with pytest.raises(core.ToolError):
        core.parse_period("next_week", None, None)


# ---------------- performance summary ----------------


async def test_performance_summary_aggregates_by_platform() -> None:
    g = FakeConnector(
        Platform.GOOGLE, currency="USD",
        campaigns=[_campaign("1", 50_000_000), _campaign("2", 30_000_000)],
    )
    reg = _registry(**{Platform.GOOGLE: g})
    result = await core.get_performance_summary(reg, period="yesterday")
    totals = result["platforms"]["google"]["totals"]
    assert totals["cost"] == 80.0
    assert totals["clicks"] == 100
    assert totals["active_campaigns"] == 2


async def test_performance_summary_unknown_platform_rejected() -> None:
    reg = _registry(**{Platform.GOOGLE: FakeConnector(Platform.GOOGLE)})
    with pytest.raises(core.ToolError):
        await core.get_performance_summary(reg, platforms=["bing"])


# ---------------- search queries ----------------


async def test_search_queries_sorted_by_cost() -> None:
    conn = FakeConnector(
        Platform.GOOGLE,
        queries=[
            _query("cheap", cost=1_000_000),
            _query("expensive", cost=10_000_000),
            _query("medium", cost=5_000_000),
        ],
    )
    reg = _registry(**{Platform.GOOGLE: conn})
    result = await core.get_search_queries(
        reg, _cfg(), platform="google", period="last_7_days", min_impressions=1,
    )
    assert [q["query"] for q in result["queries"]] == ["expensive", "medium", "cheap"]


async def test_search_queries_with_classify() -> None:
    conn = FakeConnector(
        Platform.GOOGLE,
        queries=[
            _query("что такое кредит"),
            _query("онлайн кредит"),
        ],
    )
    reg = _registry(**{Platform.GOOGLE: conn})
    result = await core.get_search_queries(
        reg, _cfg(), platform="google", classify=True, min_impressions=1,
    )
    assert "rule_flagged" in result
    # Only the informational query gets flagged
    flagged_queries = {s["query"] for s in result["rule_flagged"]}
    assert "что такое кредит" in flagged_queries
    assert "онлайн кредит" not in flagged_queries


# ---------------- negative suggestions ----------------


async def test_negative_suggestions_filters_min_spend() -> None:
    conn = FakeConnector(
        Platform.GOOGLE,
        queries=[
            _query("что такое вклад", cost=500_000),      # 0.5 USD
            _query("скачать приложение", cost=20_000_000),  # 20 USD
        ],
    )
    reg = _registry(**{Platform.GOOGLE: conn})
    result = await core.get_negative_suggestions(
        reg, _cfg(), platform="google", min_spend=5.0,
    )
    queries = {s["query"] for s in result["suggestions"]}
    assert "скачать приложение" in queries
    assert "что такое вклад" not in queries


# ---------------- apply_negatives ----------------


async def test_apply_negatives_dry_run_by_default() -> None:
    conn = FakeConnector(Platform.GOOGLE)
    reg = _registry(**{Platform.GOOGLE: conn})
    result = await core.apply_negatives(
        reg,
        platform="google",
        negatives=[
            {"keyword": "работа", "match_type": "phrase", "level": "campaign", "campaign_id": "1"}
        ],
    )
    assert result["dry_run"] is True
    assert result["applied"] == 1
    assert conn.applied_negatives[0][1] is True  # dry_run True


async def test_apply_negatives_live_flag() -> None:
    conn = FakeConnector(Platform.GOOGLE)
    reg = _registry(**{Platform.GOOGLE: conn})
    result = await core.apply_negatives(
        reg,
        platform="google",
        negatives=[{"keyword": "x", "match_type": "exact", "level": "campaign", "campaign_id": "1"}],
        dry_run=False,
    )
    assert result["dry_run"] is False
    assert conn.applied_negatives[0][1] is False


async def test_apply_negatives_invalid_match_type() -> None:
    conn = FakeConnector(Platform.GOOGLE)
    reg = _registry(**{Platform.GOOGLE: conn})
    with pytest.raises(core.ToolError):
        await core.apply_negatives(
            reg, platform="google",
            negatives=[{"keyword": "x", "match_type": "fuzzy"}],
        )


# ---------------- campaign structure ----------------


async def test_campaign_structure() -> None:
    tree = CampaignTree(
        platform=Platform.GOOGLE, account_id="acct", currency="USD",
        campaigns=[
            CampaignNode(
                id="1", name="Loans", status=CampaignStatus.ENABLED,
                daily_budget_minor=500_000_000, bidding_strategy="TCPA",
            ),
        ],
    )
    conn = FakeConnector(Platform.GOOGLE, tree=tree)
    reg = _registry(**{Platform.GOOGLE: conn})
    result = await core.get_campaign_structure(reg, platform="google")
    assert result["account_id"] == "acct"
    assert result["campaigns"][0]["daily_budget"] == 500.0


# ---------------- alerts ----------------


async def test_get_alerts_flags_overspend() -> None:
    # budget 100, spent 150 in 1d -> 50% over, warning
    conn = FakeConnector(
        Platform.GOOGLE,
        campaigns=[_campaign("1", 150_000_000, budget=100_000_000)],
    )
    reg = _registry(**{Platform.GOOGLE: conn})
    result = await core.get_alerts(reg, _cfg(), platforms=["google"], period="today")
    assert result["count"] >= 1
    assert any("overspent" in a["title"] for a in result["alerts"])


# ---------------- spend pacing ----------------


async def test_spend_pacing() -> None:
    conn = FakeConnector(
        Platform.GOOGLE,
        campaigns=[_campaign("1", 250_000_000, budget=500_000_000)],
    )
    reg = _registry(**{Platform.GOOGLE: conn})
    result = await core.get_spend_pacing(reg, platforms=["google"])
    row = result["platforms"]["google"]["campaigns"][0]
    assert row["pct_of_budget"] == 0.5
    assert result["platforms"]["google"]["total_spent"] == 250.0


# ---------------- compare platforms ----------------


async def test_compare_platforms_cpc() -> None:
    g = FakeConnector(
        Platform.GOOGLE, currency="USD",
        campaigns=[_campaign("1", 50_000_000)],  # 50USD / 50 clicks = 1.0
    )
    y = FakeConnector(
        Platform.YANDEX, currency="USD",
        campaigns=[_campaign("2", 25_000_000)],  # 0.5
    )
    reg = _registry(**{Platform.GOOGLE: g, Platform.YANDEX: y})
    result = await core.compare_platforms(reg, metric="cpc", period="last_7_days")
    assert result["platforms"]["google"]["value"] == 1.0
    assert result["platforms"]["yandex"]["value"] == 0.5
    assert result["comparable"] is True


async def test_compare_platforms_currency_mismatch_flagged() -> None:
    g = FakeConnector(Platform.GOOGLE, currency="USD", campaigns=[_campaign("1", 50_000_000)])
    y_campaign = CampaignData(
        platform=Platform.YANDEX, id="2", name="Y", status=CampaignStatus.ENABLED,
        daily_budget_minor=None, bidding_strategy=None,
        metrics=Metrics(impressions=1000, clicks=50, cost_minor=25_000_000, conversions=5),
        currency="RUB",
    )
    y = FakeConnector(Platform.YANDEX, currency="RUB", campaigns=[y_campaign])
    reg = _registry(**{Platform.GOOGLE: g, Platform.YANDEX: y})
    result = await core.compare_platforms(reg, metric="cost")
    assert result["comparable"] is False
    assert result["note"] is not None


async def test_compare_platforms_invalid_metric() -> None:
    reg = _registry(**{Platform.GOOGLE: FakeConnector(Platform.GOOGLE)})
    with pytest.raises(core.ToolError):
        await core.compare_platforms(reg, metric="vibes")
