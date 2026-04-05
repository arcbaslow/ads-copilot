"""Spend pacing checks."""

from __future__ import annotations

from ads_copilot.analyzers.alerts import Alert, Severity
from ads_copilot.config import SpendRules
from ads_copilot.models import CampaignData, CampaignStatus


def check_spend(
    campaigns: list[CampaignData],
    rules: SpendRules,
    days_in_period: int = 1,
) -> list[Alert]:
    """Flag budget pacing issues across a list of campaigns.

    - campaigns' metrics should cover `days_in_period` days ending today
    - expected spend = daily_budget * days_in_period
    """
    alerts: list[Alert] = []
    threshold = rules.daily_budget_pacing_threshold

    for c in campaigns:
        if c.status != CampaignStatus.ENABLED:
            continue

        if (
            rules.zero_spend_campaigns_alert
            and c.metrics.impressions == 0
            and c.metrics.cost_minor == 0
        ):
            alerts.append(
                Alert(
                    severity=Severity.WARNING,
                    category="spend",
                    platform=c.platform,
                    title=f'"{c.name}" had zero spend and zero impressions',
                    detail=(
                        "Active campaign produced no activity in the window. "
                        "Check targeting, bids, or ad approval status."
                    ),
                    campaign_id=c.id,
                    campaign_name=c.name,
                )
            )
            continue

        if c.daily_budget_minor is None or c.daily_budget_minor == 0:
            continue

        expected = c.daily_budget_minor * days_in_period
        actual = c.metrics.cost_minor
        pacing = (actual - expected) / expected if expected else 0.0

        if abs(pacing) < threshold:
            continue

        direction = "overspent" if pacing > 0 else "underspent"
        severity = (
            Severity.CRITICAL if abs(pacing) > threshold * 2 else Severity.WARNING
        )
        alerts.append(
            Alert(
                severity=severity,
                category="spend",
                platform=c.platform,
                title=f'"{c.name}" {direction} by {abs(pacing):.0%}',
                detail=(
                    f"Spent {actual / 1_000_000:,.2f} vs expected "
                    f"{expected / 1_000_000:,.2f} {c.currency} "
                    f"({days_in_period}d @ {c.daily_budget_minor / 1_000_000:,.2f}/day)."
                ),
                campaign_id=c.id,
                campaign_name=c.name,
                metric_values={
                    "actual_minor": actual,
                    "expected_minor": expected,
                    "pacing": pacing,
                },
            )
        )
    return alerts
