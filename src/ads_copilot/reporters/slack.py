"""Slack delivery via incoming webhook.

Uses the Block Kit format to render a structured summary with a header,
spend section, alert list, and negative suggestions.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

from ads_copilot.analyzers.alerts import Severity
from ads_copilot.reporters.formatters import AuditReport

log = logging.getLogger(__name__)


class SlackError(RuntimeError):
    pass


@dataclass(slots=True)
class SlackReporter:
    webhook_url: str
    timeout: float = 30.0

    @classmethod
    def from_env(cls, webhook_url_env: str) -> "SlackReporter":
        url = os.environ.get(webhook_url_env)
        if not url:
            raise SlackError(f"env var {webhook_url_env} is not set")
        return cls(webhook_url=url)

    async def send(
        self, report: AuditReport, client: httpx.AsyncClient | None = None
    ) -> None:
        blocks = build_blocks(report)
        owns = client is None
        http = client or httpx.AsyncClient(timeout=self.timeout)
        try:
            resp = await http.post(self.webhook_url, json={"blocks": blocks})
            if resp.status_code != 200:
                raise SlackError(
                    f"Slack webhook returned {resp.status_code}: {resp.text}"
                )
        finally:
            if owns:
                await http.aclose()


def build_blocks(report: AuditReport) -> list[dict[str, Any]]:
    """Build a Block Kit payload for an AuditReport."""
    blocks: list[dict[str, Any]] = []
    blocks.append(
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"Ads Report — {report.report_date.strftime('%b %d, %Y')} "
                f"({report.period_label})",
                "emoji": True,
            },
        }
    )

    # Spend summary
    if report.campaigns_by_platform:
        spend_lines: list[str] = []
        for platform, campaigns in report.campaigns_by_platform.items():
            total_cost = sum(c.metrics.cost_minor for c in campaigns) / 1_000_000
            total_budget = sum(c.daily_budget_minor or 0 for c in campaigns) / 1_000_000
            currency = campaigns[0].currency if campaigns else ""
            if total_budget > 0:
                pct = (total_cost / total_budget) * 100
                spend_lines.append(
                    f"*{platform.value.title()}*: {total_cost:,.0f} / "
                    f"{total_budget:,.0f} {currency} ({pct:.0f}%)"
                )
            else:
                spend_lines.append(
                    f"*{platform.value.title()}*: {total_cost:,.0f} {currency}"
                )
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": ":moneybag: *SPEND*\n" + "\n".join(spend_lines)},
            }
        )

    # Alerts
    critical = [a for a in report.alerts if a.severity == Severity.CRITICAL]
    warning = [a for a in report.alerts if a.severity == Severity.WARNING]
    total = len(critical) + len(warning)
    if total:
        alert_lines = []
        for i, a in enumerate(critical + warning, 1):
            icon = ":red_circle:" if a.severity == Severity.CRITICAL else ":warning:"
            alert_lines.append(f"{i}. {icon} {a.title}")
            if a.detail:
                alert_lines.append(f"   _{a.detail}_")
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":rotating_light: *ALERTS ({total})*\n" + "\n".join(alert_lines),
                },
            }
        )

    # Negatives
    if report.negative_suggestions:
        top = report.negative_suggestions[:5]
        lines = [
            f"`{s.query}` — {s.clicks} clicks, "
            f"{s.cost_minor / 1_000_000:.2f} spend ({s.category})"
            for s in top
        ]
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f":mag: *SEARCH QUERIES* "
                        f"(reviewed {report.queries_reviewed}, "
                        f"{len(report.negative_suggestions)} to negate)\n"
                        + "\n".join(lines)
                    ),
                },
            }
        )

    if total == 0 and not report.negative_suggestions:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": ":white_check_mark: No alerts. Everything looks healthy.",
                },
            }
        )

    return blocks
