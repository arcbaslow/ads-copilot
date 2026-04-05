from ads_copilot.analyzers.performance import detect_anomalies
from ads_copilot.config import PerformanceRules
from ads_copilot.models import CampaignData, CampaignStatus, Metrics, Platform


def _c(
    cid: str = "1",
    impressions: int = 1000,
    clicks: int = 50,
    cost: int = 50_000_000,
    conversions: float = 5.0,
) -> CampaignData:
    return CampaignData(
        platform=Platform.GOOGLE,
        id=cid,
        name=f"Campaign {cid}",
        status=CampaignStatus.ENABLED,
        daily_budget_minor=None,
        bidding_strategy=None,
        metrics=Metrics(
            impressions=impressions, clicks=clicks, cost_minor=cost, conversions=conversions
        ),
        currency="USD",
    )


def test_ctr_drop_flagged() -> None:
    rules = PerformanceRules(ctr_drop_threshold=0.3)
    # prior CTR = 50/1000 = 5%, current = 10/1000 = 1% — 80% drop
    current = [_c(impressions=1000, clicks=10)]
    prior = {"1": Metrics(impressions=1000, clicks=50, cost_minor=50_000_000, conversions=5)}
    alerts = detect_anomalies(current, prior, rules)
    assert len(alerts) >= 1
    assert any("CTR" in a.title and "dropped" in a.title for a in alerts)


def test_cpc_spike_flagged() -> None:
    rules = PerformanceRules(cpc_spike_threshold=0.5)
    # prior CPC = 50M/50 = 1M, current = 200M/50 = 4M — 300% spike
    current = [_c(impressions=1000, clicks=50, cost=200_000_000)]
    prior = {"1": Metrics(impressions=1000, clicks=50, cost_minor=50_000_000, conversions=5)}
    alerts = detect_anomalies(current, prior, rules)
    assert any("CPC" in a.title and "spiked" in a.title for a in alerts)


def test_insufficient_data_skipped() -> None:
    rules = PerformanceRules()
    current = [_c(impressions=50)]  # below MIN_IMPRESSIONS
    prior = {"1": Metrics(impressions=5000, clicks=100, cost_minor=100_000_000, conversions=5)}
    assert detect_anomalies(current, prior, rules) == []


def test_no_prior_data_skipped() -> None:
    rules = PerformanceRules()
    current = [_c()]
    assert detect_anomalies(current, {}, rules) == []


def test_stable_campaign_no_alert() -> None:
    rules = PerformanceRules()
    current = [_c(impressions=1000, clicks=50, cost=50_000_000)]
    prior = {"1": Metrics(impressions=1000, clicks=48, cost_minor=52_000_000, conversions=5)}
    assert detect_anomalies(current, prior, rules) == []
