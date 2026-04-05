"""Audit orchestrator — pulls data, runs analyzers, builds an AuditReport.

This is the entry point the CLI and scheduler both call into.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from ads_copilot.ai.bridge import ai_to_suggestions
from ads_copilot.ai.query_intent import QueryClassifier
from ads_copilot.analyzers.alerts import Alert
from ads_copilot.analyzers.negative_finder import (
    RuleBasedQueryFilter,
    Suggestion,
)
from ads_copilot.analyzers.performance import detect_anomalies
from ads_copilot.analyzers.spend_checker import check_spend
from ads_copilot.config import Config
from ads_copilot.connectors.base import AdPlatformConnector
from ads_copilot.models import CampaignData, DateRange, Platform, SearchQueryData
from ads_copilot.reporters.formatters import AuditReport
from ads_copilot.storage import SnapshotStore

# Hard cap on how many queries we send to the LLM per account. AI costs money;
# the rule layer should already catch the obvious negatives.
MAX_AI_QUERIES_PER_ACCOUNT = 200

log = logging.getLogger(__name__)


async def run_audit(
    cfg: Config,
    connectors: list[AdPlatformConnector],
    period: DateRange,
    period_label: str,
    store: SnapshotStore | None = None,
    classifier: QueryClassifier | None = None,
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
        rule_suggestions = rule_filter.classify(queries)
        all_suggestions.extend(rule_suggestions)

        # AI classification on what rules couldn't handle
        if classifier is not None:
            rule_flagged = {s.query for s in rule_suggestions}
            candidates = _ai_candidates(
                queries,
                already_flagged=rule_flagged,
                min_impressions=cfg.ai.classify_threshold_impressions,
            )
            if candidates:
                log.info(
                    "sending %d queries to AI classifier for %s",
                    len(candidates), connector.platform.value,
                )
                classified = classifier.classify(candidates)
                all_suggestions.extend(ai_to_suggestions(classified))

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


def _ai_candidates(
    queries: list[SearchQueryData],
    already_flagged: set[str],
    min_impressions: int,
) -> list[SearchQueryData]:
    """Pick queries worth spending AI tokens on.

    Criteria: not already flagged by rules, meets impression threshold, has
    spend or clicks, and zero conversions (converters are self-evidently
    relevant). Ranked by cost so the worst offenders go first.
    """
    candidates = [
        q for q in queries
        if q.query not in already_flagged
        and q.metrics.impressions >= min_impressions
        and q.metrics.conversions == 0
        and (q.metrics.cost_minor > 0 or q.metrics.clicks > 0)
    ]
    candidates.sort(key=lambda q: -q.metrics.cost_minor)
    return candidates[:MAX_AI_QUERIES_PER_ACCOUNT]
