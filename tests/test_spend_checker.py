from ads_copilot.analyzers.alerts import Severity
from ads_copilot.analyzers.spend_checker import check_spend
from ads_copilot.config import SpendRules
from ads_copilot.models import CampaignData, CampaignStatus, Metrics, Platform


def _c(
    name: str,
    cost: int,
    budget: int | None,
    impressions: int = 100,
    status: CampaignStatus = CampaignStatus.ENABLED,
) -> CampaignData:
    return CampaignData(
        platform=Platform.GOOGLE,
        id=name,
        name=name,
        status=status,
        daily_budget_minor=budget,
        bidding_strategy=None,
        metrics=Metrics(impressions=impressions, clicks=10, cost_minor=cost),
        currency="USD",
    )


def test_overspent_triggers_warning() -> None:
    rules = SpendRules(daily_budget_pacing_threshold=0.2)
    # budget 100, 1 day -> expected 100. actual 130 (30% over)
    alerts = check_spend([_c("A", 130_000_000, 100_000_000)], rules, days_in_period=1)
    assert len(alerts) == 1
    assert alerts[0].severity == Severity.WARNING
    assert "overspent" in alerts[0].title


def test_big_overspend_is_critical() -> None:
    rules = SpendRules(daily_budget_pacing_threshold=0.2)
    alerts = check_spend([_c("A", 200_000_000, 100_000_000)], rules, days_in_period=1)
    assert alerts[0].severity == Severity.CRITICAL


def test_underspend_flagged() -> None:
    rules = SpendRules(daily_budget_pacing_threshold=0.2)
    alerts = check_spend([_c("A", 50_000_000, 100_000_000)], rules, days_in_period=1)
    assert len(alerts) == 1
    assert "underspent" in alerts[0].title


def test_within_threshold_no_alert() -> None:
    rules = SpendRules(daily_budget_pacing_threshold=0.2)
    alerts = check_spend([_c("A", 110_000_000, 100_000_000)], rules, days_in_period=1)
    assert alerts == []


def test_zero_spend_alert() -> None:
    rules = SpendRules(zero_spend_campaigns_alert=True)
    alerts = check_spend(
        [_c("A", 0, 100_000_000, impressions=0)], rules, days_in_period=1
    )
    assert len(alerts) == 1
    assert "zero spend" in alerts[0].title


def test_paused_campaigns_ignored() -> None:
    rules = SpendRules()
    alerts = check_spend(
        [_c("A", 200_000_000, 100_000_000, status=CampaignStatus.PAUSED)],
        rules, days_in_period=1,
    )
    assert alerts == []


def test_multi_day_period_scales_budget() -> None:
    rules = SpendRules(daily_budget_pacing_threshold=0.2)
    # 7d * 100 budget = 700 expected. Actual 750 is 7% over — no alert.
    alerts = check_spend(
        [_c("A", 750_000_000, 100_000_000)], rules, days_in_period=7
    )
    assert alerts == []
