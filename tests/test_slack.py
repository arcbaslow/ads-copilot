from datetime import date

from ads_copilot.analyzers.alerts import Alert, Severity
from ads_copilot.analyzers.negative_finder import Suggestion
from ads_copilot.models import CampaignData, CampaignStatus, MatchType, Metrics, Platform
from ads_copilot.reporters.formatters import AuditReport
from ads_copilot.reporters.slack import build_blocks


def _report(
    *, alerts: list[Alert] | None = None,
    suggestions: list[Suggestion] | None = None,
    campaigns: list[CampaignData] | None = None,
) -> AuditReport:
    return AuditReport(
        report_date=date(2026, 4, 5),
        period_label="today",
        campaigns_by_platform={Platform.GOOGLE: campaigns or []} if campaigns else {},
        alerts=alerts or [],
        negative_suggestions=suggestions or [],
        queries_reviewed=0,
    )


def _c(cost: int, budget: int) -> CampaignData:
    return CampaignData(
        platform=Platform.GOOGLE, id="1", name="C", status=CampaignStatus.ENABLED,
        daily_budget_minor=budget, bidding_strategy=None,
        metrics=Metrics(impressions=100, clicks=5, cost_minor=cost),
        currency="USD",
    )


def test_header_block_always_present() -> None:
    blocks = build_blocks(_report())
    assert blocks[0]["type"] == "header"
    assert "Ads Report" in blocks[0]["text"]["text"]


def test_spend_section_shows_pct_of_budget() -> None:
    blocks = build_blocks(_report(campaigns=[_c(450_000_000, 500_000_000)]))
    spend = next(b for b in blocks if "SPEND" in b.get("text", {}).get("text", ""))
    assert "90%" in spend["text"]["text"]


def test_alerts_critical_before_warning() -> None:
    alerts = [
        Alert(Severity.WARNING, "spend", Platform.GOOGLE, "W1", ""),
        Alert(Severity.CRITICAL, "spend", Platform.GOOGLE, "C1", ""),
    ]
    blocks = build_blocks(_report(alerts=alerts))
    text = next(b for b in blocks if "ALERTS" in b.get("text", {}).get("text", ""))["text"]["text"]
    assert text.index("C1") < text.index("W1")


def test_empty_report_shows_all_clear() -> None:
    blocks = build_blocks(_report())
    text = " ".join(b.get("text", {}).get("text", "") for b in blocks)
    assert "healthy" in text.lower()


def test_negatives_top_5_shown() -> None:
    suggestions = [
        Suggestion(
            query=f"q{i}", match_type=MatchType.PHRASE, level="campaign",
            campaign_id="1", adgroup_id=None, reason="x", category="job_seekers",
            cost_minor=10_000_000 - i, clicks=3, conversions=0,
        )
        for i in range(10)
    ]
    blocks = build_blocks(_report(suggestions=suggestions))
    text = next(b for b in blocks if "SEARCH QUERIES" in b.get("text", {}).get("text", ""))["text"]["text"]
    # top 5 only
    assert text.count("q0") >= 1
    assert "q6" not in text
