from datetime import date, datetime, timedelta

from ads_copilot.analyzers.performance import detect_anomalies, within_conversion_lag
from ads_copilot.config import ConversionsRules, PerformanceRules
from ads_copilot.models import CampaignData, CampaignStatus, DateRange, Metrics, Platform


def test_period_ending_today_is_within_lag() -> None:
    today = date.today()
    period = DateRange(start=today - timedelta(days=1), end=today)
    rules = ConversionsRules(conversion_lag_hours=48)
    # current moment is within 48h of end-of-day-today
    assert within_conversion_lag(period, rules) is True


def test_old_period_is_outside_lag() -> None:
    period = DateRange(
        start=date(2026, 1, 1), end=date(2026, 1, 7),
    )
    rules = ConversionsRules(conversion_lag_hours=48)
    # Using real now — a period from months ago is definitely past lag
    assert within_conversion_lag(period, rules) is False


def test_custom_now_crosses_threshold() -> None:
    period = DateRange(start=date(2026, 4, 1), end=date(2026, 4, 2))
    rules = ConversionsRules(conversion_lag_hours=24)
    # End-of-day Apr 2 = Apr 3 00:00. 22h later: still within lag
    assert within_conversion_lag(period, rules, now=datetime(2026, 4, 3, 22, 0)) is True
    # 25h later: past lag
    assert within_conversion_lag(period, rules, now=datetime(2026, 4, 4, 1, 0)) is False


def test_skip_cpa_suppresses_cpa_alerts() -> None:
    rules = PerformanceRules(cpa_spike_threshold=0.5)
    current = [
        CampaignData(
            platform=Platform.GOOGLE, id="1", name="C",
            status=CampaignStatus.ENABLED, daily_budget_minor=None,
            bidding_strategy=None,
            metrics=Metrics(
                impressions=1000, clicks=50, cost_minor=200_000_000, conversions=2,
            ),
            currency="USD",
        )
    ]
    prior = {
        "1": Metrics(
            impressions=1000, clicks=50, cost_minor=50_000_000, conversions=5,
        )
    }
    # Without skip: CPA spikes massively (25M -> 100M, 300% up)
    alerts_normal = detect_anomalies(current, prior, rules, skip_cpa=False)
    assert any("CPA" in a.title for a in alerts_normal)
    # With skip: CPA alert is suppressed, but CTR/CPC checks still run
    alerts_skipped = detect_anomalies(current, prior, rules, skip_cpa=True)
    assert not any("CPA" in a.title for a in alerts_skipped)
