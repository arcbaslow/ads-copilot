"""Verify that one connector failing doesn't kill the whole audit."""

from datetime import date, timedelta

from ads_copilot.analyzers.alerts import Severity
from ads_copilot.audit import run_audit
from ads_copilot.config import (
    AccountsConfig,
    BusinessConfig,
    Config,
    YandexDirectAccount,
)
from ads_copilot.models import (
    CampaignData,
    CampaignStatus,
    DateRange,
    Metrics,
    Platform,
)
from tests.fakes import FakeConnector


def _cfg() -> Config:
    return Config(
        accounts=AccountsConfig(
            yandex_direct=[YandexDirectAccount(name="t", login="t", token_env="X")]
        ),
        business=BusinessConfig(currency="USD"),
    )


def _healthy_campaign() -> CampaignData:
    return CampaignData(
        platform=Platform.GOOGLE, id="1", name="Healthy",
        status=CampaignStatus.ENABLED, daily_budget_minor=100_000_000,
        bidding_strategy="TCPA",
        metrics=Metrics(impressions=500, clicks=20, cost_minor=90_000_000, conversions=2),
        currency="USD",
    )


class ExplodingConnector(FakeConnector):
    """FakeConnector that raises on get_campaigns."""

    async def get_campaigns(self, period):  # type: ignore[no-untyped-def]
        raise RuntimeError("API on fire")


async def test_one_connector_failure_does_not_stop_audit() -> None:
    today = date.today()
    period = DateRange(start=today - timedelta(days=1), end=today)
    healthy = FakeConnector(
        Platform.GOOGLE, currency="USD", campaigns=[_healthy_campaign()],
    )
    broken = ExplodingConnector(Platform.YANDEX, currency="RUB")

    report = await run_audit(
        _cfg(), [broken, healthy], period, period_label="1d",
    )

    # The healthy connector still produced data
    assert Platform.GOOGLE in report.campaigns_by_platform
    assert len(report.campaigns_by_platform[Platform.GOOGLE]) == 1

    # And the broken one produced a CRITICAL connector alert
    connector_alerts = [a for a in report.alerts if a.category == "connector"]
    assert len(connector_alerts) == 1
    assert connector_alerts[0].severity == Severity.CRITICAL
    assert connector_alerts[0].platform == Platform.YANDEX
    assert "RuntimeError" in connector_alerts[0].title


async def test_structure_failure_is_isolated() -> None:
    """Structure audit failure shouldn't fail the whole connector pass."""
    today = date.today()
    period = DateRange(start=today - timedelta(days=1), end=today)

    class NoStructureConnector(FakeConnector):
        async def get_campaign_structure(self):  # type: ignore[no-untyped-def]
            raise RuntimeError("structure endpoint broken")

    conn = NoStructureConnector(
        Platform.GOOGLE, currency="USD", campaigns=[_healthy_campaign()],
    )
    report = await run_audit(_cfg(), [conn], period, period_label="1d")

    # The connector as a whole is still considered healthy
    assert Platform.GOOGLE in report.campaigns_by_platform
    assert not any(a.category == "connector" for a in report.alerts)
