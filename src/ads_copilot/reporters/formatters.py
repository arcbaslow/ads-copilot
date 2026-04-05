"""Cross-channel message formatters for audit summaries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ads_copilot.analyzers.alerts import Alert, Severity
from ads_copilot.analyzers.negative_finder import Suggestion
from ads_copilot.models import CampaignData, Platform


@dataclass(slots=True)
class AuditReport:
    report_date: date
    period_label: str
    campaigns_by_platform: dict[Platform, list[CampaignData]]
    alerts: list[Alert]
    negative_suggestions: list[Suggestion]
    queries_reviewed: int = 0


def _money(minor: int, currency: str) -> str:
    return f"{minor / 1_000_000:,.0f} {currency}"


def format_telegram(report: AuditReport) -> str:
    """Render an audit report as a Telegram message (HTML parse mode)."""
    lines: list[str] = []
    lines.append(
        f"📊 <b>Ads Report</b> | {report.report_date.strftime('%b %d, %Y')} "
        f"({report.period_label})"
    )
    lines.append("")

    # Spend section
    if report.campaigns_by_platform:
        lines.append("💰 <b>SPEND</b>")
        for platform, campaigns in report.campaigns_by_platform.items():
            total = _platform_spend(campaigns)
            budget = _platform_budget(campaigns)
            if budget > 0:
                pct = total / budget
                lines.append(
                    f"{platform.value.title()}: "
                    f"{_money(total, _cur(campaigns))} / "
                    f"{_money(budget, _cur(campaigns))} ({pct:.0%})"
                )
            else:
                lines.append(
                    f"{platform.value.title()}: {_money(total, _cur(campaigns))}"
                )
        lines.append("")

    # Alerts section
    critical = [a for a in report.alerts if a.severity == Severity.CRITICAL]
    warning = [a for a in report.alerts if a.severity == Severity.WARNING]
    total_alerts = len(critical) + len(warning)
    if total_alerts:
        lines.append(f"⚠️ <b>ALERTS ({total_alerts})</b>")
        for i, a in enumerate(critical + warning, 1):
            lines.append(f"{i}. {a.severity.icon} {a.title}")
            if a.detail:
                lines.append(f"   <i>{a.detail}</i>")
        lines.append("")

    # Negatives section
    if report.negative_suggestions:
        high_conf = [
            s for s in report.negative_suggestions if s.clicks >= 3 or s.cost_minor > 5_000_000
        ]
        lines.append(f"🔍 <b>SEARCH QUERIES</b> (reviewed {report.queries_reviewed})")
        lines.append(f"Negatives to add: {len(high_conf)} (high confidence)")
        if high_conf:
            lines.append("Top wasted-spend candidates:")
            for s in high_conf[:5]:
                lines.append(
                    f"  • <code>{s.query}</code> "
                    f"({s.clicks} clicks, {s.cost_minor / 1_000_000:.2f} spend) — {s.category}"
                )
        lines.append("")

    if total_alerts == 0 and not report.negative_suggestions:
        lines.append("✅ No alerts. Everything looks healthy.")

    return "\n".join(lines).rstrip()


def format_markdown(report: AuditReport) -> str:
    """Render an audit report as markdown."""
    lines: list[str] = []
    lines.append(
        f"# Ads Report — {report.report_date.strftime('%b %d, %Y')} "
        f"({report.period_label})"
    )
    lines.append("")

    if report.campaigns_by_platform:
        lines.append("## Spend")
        lines.append("")
        lines.append("| Platform | Campaign | Spend | Daily Budget |")
        lines.append("|---|---|---:|---:|")
        for platform, campaigns in report.campaigns_by_platform.items():
            for c in campaigns:
                budget = (
                    _money(c.daily_budget_minor, c.currency)
                    if c.daily_budget_minor else "-"
                )
                lines.append(
                    f"| {platform.value} | {c.name} | "
                    f"{_money(c.metrics.cost_minor, c.currency)} | {budget} |"
                )
        lines.append("")

    if report.alerts:
        lines.append("## Alerts")
        lines.append("")
        for a in report.alerts:
            lines.append(f"- **[{a.severity.value.upper()}] {a.category}**: {a.title}")
            if a.detail:
                lines.append(f"  - {a.detail}")
        lines.append("")

    if report.negative_suggestions:
        lines.append(f"## Negative keyword suggestions ({len(report.negative_suggestions)})")
        lines.append("")
        lines.append("| Query | Clicks | Cost | Match | Scope | Reason |")
        lines.append("|---|---:|---:|---|---|---|")
        for s in report.negative_suggestions[:50]:
            scope = s.level
            if s.campaign_id:
                scope = f"{s.level}:{s.campaign_id}"
            lines.append(
                f"| `{s.query}` | {s.clicks} | "
                f"{s.cost_minor / 1_000_000:.2f} | {s.match_type.value} | "
                f"{scope} | {s.category} |"
            )
        lines.append("")
    return "\n".join(lines)


def _platform_spend(campaigns: list[CampaignData]) -> int:
    return sum(c.metrics.cost_minor for c in campaigns)


def _platform_budget(campaigns: list[CampaignData]) -> int:
    return sum(c.daily_budget_minor or 0 for c in campaigns)


def _cur(campaigns: list[CampaignData]) -> str:
    return campaigns[0].currency if campaigns else ""
