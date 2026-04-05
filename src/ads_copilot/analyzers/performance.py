"""Period-over-period anomaly detection.

Compares current window to an equal-length prior window and flags
CTR drops / CPC spikes / CPA spikes above configured thresholds.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from ads_copilot.analyzers.alerts import Alert, Severity
from ads_copilot.config import ConversionsRules, PerformanceRules
from ads_copilot.models import CampaignData, DateRange, Metrics

log = logging.getLogger(__name__)

# Filter out campaigns with too little data — swings on tiny denominators
# are noise, not signal.
MIN_IMPRESSIONS = 200
MIN_CLICKS = 20


def within_conversion_lag(
    period: DateRange,
    conversion_rules: ConversionsRules,
    now: datetime | None = None,
) -> bool:
    """Return True if the period ends too recently to trust conversion data.

    Conversions lag by hours (Google) or can take up to 30 days (Yandex
    offline conversions). Running CPA comparisons against an incomplete
    conversion signal produces false alerts.
    """
    now = now or datetime.now()
    # Treat the period end as end-of-day
    period_end = datetime.combine(
        period.end, datetime.min.time()
    ) + timedelta(days=1)
    return (now - period_end) < timedelta(hours=conversion_rules.conversion_lag_hours)


def detect_anomalies(
    current: list[CampaignData],
    prior: dict[str, Metrics],
    rules: PerformanceRules,
    *,
    skip_cpa: bool = False,
) -> list[Alert]:
    """Compare each current-period campaign to its prior-period aggregate.

    If skip_cpa is True, CPA-spike checks are skipped — use this when the
    current period hasn't passed the conversion-reporting lag window.
    """
    alerts: list[Alert] = []

    for c in current:
        cur = c.metrics
        if cur.impressions < MIN_IMPRESSIONS:
            continue
        prev = prior.get(c.id)
        if prev is None or prev.impressions < MIN_IMPRESSIONS:
            continue

        # CTR drop
        if prev.ctr > 0:
            delta = (cur.ctr - prev.ctr) / prev.ctr
            if delta < -rules.ctr_drop_threshold:
                alerts.append(
                    _build_alert(
                        c, "CTR",
                        delta,
                        f"{prev.ctr:.2%} -> {cur.ctr:.2%}",
                        direction="dropped",
                        severity=_sev(abs(delta), rules.ctr_drop_threshold),
                    )
                )

        # CPC spike
        if prev.clicks >= MIN_CLICKS and cur.clicks >= MIN_CLICKS and prev.cpc_minor > 0:
            delta = (cur.cpc_minor - prev.cpc_minor) / prev.cpc_minor
            if delta > rules.cpc_spike_threshold:
                alerts.append(
                    _build_alert(
                        c, "CPC", delta,
                        f"{prev.cpc_minor / 1_000_000:.2f} -> "
                        f"{cur.cpc_minor / 1_000_000:.2f} {c.currency}",
                        direction="spiked",
                        severity=_sev(delta, rules.cpc_spike_threshold),
                    )
                )

        # CPA spike
        if (
            not skip_cpa
            and prev.conversions > 0
            and cur.conversions > 0
            and prev.cpa_minor > 0
        ):
            delta = (cur.cpa_minor - prev.cpa_minor) / prev.cpa_minor
            if delta > rules.cpa_spike_threshold:
                alerts.append(
                    _build_alert(
                        c, "CPA", delta,
                        f"{prev.cpa_minor / 1_000_000:,.2f} -> "
                        f"{cur.cpa_minor / 1_000_000:,.2f} {c.currency}",
                        direction="spiked",
                        severity=_sev(delta, rules.cpa_spike_threshold),
                    )
                )

    return alerts


def _sev(abs_delta: float, threshold: float) -> Severity:
    return Severity.CRITICAL if abs_delta > threshold * 2 else Severity.WARNING


def _build_alert(
    c: CampaignData,
    metric: str,
    delta: float,
    values_str: str,
    *,
    direction: str,
    severity: Severity,
) -> Alert:
    return Alert(
        severity=severity,
        category="performance",
        platform=c.platform,
        title=f'"{c.name}" {metric} {direction} {abs(delta):.0%}',
        detail=f"{values_str} vs prior period",
        campaign_id=c.id,
        campaign_name=c.name,
        metric_values={"metric": metric, "delta": delta},
    )
