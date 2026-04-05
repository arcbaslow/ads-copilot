"""Audit orchestrator — pulls data, runs analyzers, builds an AuditReport.

This is the entry point the CLI and scheduler both call into.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from ads_copilot.analyzers.alerts import Alert
from ads_copilot.analyzers.negative_finder import (
    RuleBasedQueryFilter,
    Suggestion,
)
from ads_copilot.analyzers.performance import detect_anomalies
from ads_copilot.analyzers.spend_checker import check_spend
from ads_copilot.config import Config
from ads_copilot.connectors.base import AdPlatformConnector
from ads_copilot.models import CampaignData, DateRange, Platform
from ads_copilot.reporters.formatters import AuditReport
from ads_copilot.storage import SnapshotStore

log = logging.getLogger(__name__)


async def run_audit(
    cfg: Config,
    connectors: list[AdPlatformConnector],
    period: DateRange,
    period_label: str,
    store: SnapshotStore | None = None,
) -> AuditReport:
    days = (period.end - period.start).days + 1
    prior = DateRange(
        start=period.start - timedelta(days=days),
        end=period.start - timedelta(days=1),
    )

    campaigns_by_platform: dict[Platform, list[CampaignData]] = {}
    all_alerts: list[Alert] = []
    all_suggestions: list[Suggestion] = []
    queries_reviewed = 0

    rule_filter = RuleBasedQueryFilter(
        custom_patterns=cfg.negative_keywords.custom_patterns,
        min_impressions=cfg.rules.search_queries.min_impressions_for_review,
    )

    for connector in connectors:
        log.info("auditing %s account %s", connector.platform.value, connector.account_id)
        campaigns = await connector.get_campaigns(period)
        campaigns_by_platform.setdefault(connector.platform, []).extend(campaigns)

        # Spend pacing
        spend_alerts = check_spend(campaigns, cfg.rules.spend, days_in_period=days)
        all_alerts.extend(spend_alerts)

        # Performance anomalies (requires snapshot history)
        if store is not None:
            store.write(connector.account_id, date.today(), campaigns)
            prior_metrics = store.aggregate(
                connector.platform, connector.account_id, prior.start, prior.end
            )
            if prior_metrics:
                all_alerts.extend(
                    detect_anomalies(campaigns, prior_metrics, cfg.rules.performance)
                )
            else:
                log.info(
                    "no prior snapshots for %s — skipping anomaly detection",
                    connector.platform.value,
                )

        # Search queries
        queries = await connector.get_search_queries(
            period,
            min_impressions=cfg.rules.search_queries.min_impressions_for_review,
        )
        queries_reviewed += len(queries)
        all_suggestions.extend(rule_filter.classify(queries))

    all_alerts.sort(key=lambda a: a.sort_key())
    all_suggestions.sort(key=lambda s: -s.cost_minor)

    return AuditReport(
        report_date=date.today(),
        period_label=period_label,
        campaigns_by_platform=campaigns_by_platform,
        alerts=all_alerts,
        negative_suggestions=all_suggestions,
        queries_reviewed=queries_reviewed,
    )
