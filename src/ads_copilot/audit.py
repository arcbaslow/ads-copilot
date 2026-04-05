"""Audit orchestrator — pulls data, runs analyzers, builds an AuditReport.

This is the entry point the CLI and scheduler both call into.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from ads_copilot.ai.bridge import ai_to_suggestions
from ads_copilot.ai.query_intent import QueryClassifier
from ads_copilot.analyzers.alerts import Alert, Severity
from ads_copilot.analyzers.negative_finder import (
    RuleBasedQueryFilter,
    Suggestion,
)
from ads_copilot.analyzers.performance import detect_anomalies, within_conversion_lag
from ads_copilot.analyzers.spend_checker import check_spend
from ads_copilot.analyzers.structure_audit import audit_structure
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
    account_label: str | None = None,
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
        brand_patterns=cfg.negative_keywords.brand_patterns,
        competitor_patterns=cfg.negative_keywords.competitor_patterns,
        min_impressions=cfg.rules.search_queries.min_impressions_for_review,
    )

    skip_cpa = within_conversion_lag(period, cfg.rules.conversions)
    if skip_cpa:
        log.info(
            "period ends within conversion_lag_hours (%d) — skipping CPA checks",
            cfg.rules.conversions.conversion_lag_hours,
        )

    for connector in connectors:
        log.info("auditing %s account %s", connector.platform.value, connector.account_id)
        try:
            conn_alerts, conn_suggestions, conn_campaigns, conn_query_count = (
                await _audit_one_connector(
                    connector, cfg, period, days, prior, store,
                    rule_filter, classifier, skip_cpa,
                )
            )
        except Exception as e:
            log.exception(
                "%s audit failed: %s", connector.platform.value, e
            )
            all_alerts.append(
                Alert(
                    severity=Severity.CRITICAL,
                    category="connector",
                    platform=connector.platform,
                    title=(
                        f"{connector.platform.value.title()} audit failed: "
                        f"{type(e).__name__}"
                    ),
                    detail=f"{e}. Remaining platforms continue normally.",
                )
            )
            continue

        campaigns_by_platform.setdefault(connector.platform, []).extend(conn_campaigns)
        all_alerts.extend(conn_alerts)
        all_suggestions.extend(conn_suggestions)
        queries_reviewed += conn_query_count

    all_alerts.sort(key=lambda a: a.sort_key())
    all_suggestions.sort(key=lambda s: -s.cost_minor)

    return AuditReport(
        report_date=date.today(),
        period_label=period_label,
        campaigns_by_platform=campaigns_by_platform,
        alerts=all_alerts,
        negative_suggestions=all_suggestions,
        queries_reviewed=queries_reviewed,
        account_label=account_label,
    )


async def _audit_one_connector(
    connector: AdPlatformConnector,
    cfg: Config,
    period: DateRange,
    days: int,
    prior: DateRange,
    store: SnapshotStore | None,
    rule_filter: RuleBasedQueryFilter,
    classifier: QueryClassifier | None,
    skip_cpa: bool,
) -> tuple[list[Alert], list[Suggestion], list[CampaignData], int]:
    """Run the full analyzer stack for one connector. Returns
    (alerts, suggestions, campaigns, queries_reviewed). Exceptions bubble
    up so the caller can emit a connector-level failure alert."""
    alerts: list[Alert] = []
    suggestions: list[Suggestion] = []

    campaigns = await connector.get_campaigns(period)

    alerts.extend(check_spend(campaigns, cfg.rules.spend, days_in_period=days))

    if store is not None:
        store.write(connector.account_id, date.today(), campaigns)
        prior_metrics = store.aggregate(
            connector.platform, connector.account_id, prior.start, prior.end
        )
        if prior_metrics:
            alerts.extend(
                detect_anomalies(
                    campaigns, prior_metrics, cfg.rules.performance,
                    skip_cpa=skip_cpa,
                )
            )
        else:
            log.info(
                "no prior snapshots for %s — skipping anomaly detection",
                connector.platform.value,
            )

    # Structure audit — independent failure, don't let it kill the audit
    try:
        tree = await connector.get_campaign_structure()
        alerts.extend(audit_structure(tree, cfg.rules.structure))
    except Exception as e:
        log.warning("structure audit failed for %s: %s", connector.platform.value, e)

    queries = await connector.get_search_queries(
        period,
        min_impressions=cfg.rules.search_queries.min_impressions_for_review,
    )
    rule_suggestions = rule_filter.classify(queries)
    suggestions.extend(rule_suggestions)

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
            suggestions.extend(ai_to_suggestions(classified))

    return alerts, suggestions, campaigns, len(queries)


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
