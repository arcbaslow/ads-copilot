from datetime import date

from ads_copilot.analyzers.alerts import Alert, Severity
from ads_copilot.analyzers.negative_finder import Suggestion
from ads_copilot.models import CampaignData, CampaignStatus, MatchType, Metrics, Platform
from ads_copilot.reporters.formatters import AuditReport, format_markdown, format_telegram


def _sample_report() -> AuditReport:
    c = CampaignData(
        platform=Platform.GOOGLE,
        id="1",
        name="Loans",
        status=CampaignStatus.ENABLED,
        daily_budget_minor=500_000_000,
        bidding_strategy="TargetCPA",
        metrics=Metrics(impressions=1000, clicks=50, cost_minor=450_000_000, conversions=3),
        currency="USD",
    )
    return AuditReport(
        report_date=date(2026, 4, 5),
        period_label="last 7d",
        campaigns_by_platform={Platform.GOOGLE: [c]},
        alerts=[
            Alert(
                severity=Severity.CRITICAL,
                category="performance",
                platform=Platform.GOOGLE,
                title='"Loans" CPA spiked 80%',
                detail="40 -> 72 USD vs prior period",
                campaign_id="1",
                campaign_name="Loans",
            )
        ],
        negative_suggestions=[
            Suggestion(
                query="работа в банке",
                match_type=MatchType.PHRASE,
                level="adgroup",
                campaign_id="1",
                adgroup_id="10",
                reason="matches rule: job_seekers",
                category="job_seekers",
                cost_minor=8_000_000,
                clicks=5,
                conversions=0.0,
            )
        ],
        queries_reviewed=200,
    )


def test_telegram_format_has_key_sections() -> None:
    out = format_telegram(_sample_report())
    assert "Ads Report" in out
    assert "SPEND" in out
    assert "ALERTS (1)" in out
    assert "CPA spiked" in out
    assert "работа в банке" in out
    assert "job_seekers" in out


def test_telegram_healthy_report() -> None:
    r = AuditReport(
        report_date=date(2026, 4, 5),
        period_label="today",
        campaigns_by_platform={},
        alerts=[],
        negative_suggestions=[],
    )
    out = format_telegram(r)
    assert "No alerts" in out


def test_markdown_format_has_tables() -> None:
    out = format_markdown(_sample_report())
    assert "# Ads Report" in out
    assert "| Platform |" in out
    assert "| Query |" in out
    assert "работа в банке" in out
