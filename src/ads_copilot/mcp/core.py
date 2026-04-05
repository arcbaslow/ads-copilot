"""Core MCP tool implementations.

These are plain async functions that return JSON-serializable dicts. The
FastMCP wrapper in server.py registers them as tools; tests import them
directly without needing the mcp SDK.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from ads_copilot.analyzers.negative_finder import RuleBasedQueryFilter
from ads_copilot.analyzers.performance import detect_anomalies
from ads_copilot.analyzers.spend_checker import check_spend
from ads_copilot.config import Config
from ads_copilot.mcp.registry import ConnectorRegistry
from ads_copilot.models import (
    DateRange,
    MatchType,
    NegativeKeyword,
    Platform,
)
from ads_copilot.storage import SnapshotStore

log = logging.getLogger(__name__)

VALID_PERIODS = {"today", "yesterday", "last_7_days", "last_30_days", "custom"}


class ToolError(ValueError):
    pass


def parse_period(
    period: str, date_from: str | None, date_to: str | None
) -> tuple[DateRange, str]:
    """Resolve a period string to a DateRange + human label."""
    today = date.today()
    if period == "custom":
        if not date_from or not date_to:
            raise ToolError("custom period requires date_from and date_to (YYYY-MM-DD)")
        return (
            DateRange(start=date.fromisoformat(date_from), end=date.fromisoformat(date_to)),
            f"{date_from} to {date_to}",
        )
    if period == "today":
        return DateRange(start=today, end=today), "today"
    if period == "yesterday":
        y = today - timedelta(days=1)
        return DateRange(start=y, end=y), "yesterday"
    if period == "last_7_days":
        return DateRange(start=today - timedelta(days=7), end=today), "last 7 days"
    if period == "last_30_days":
        return DateRange(start=today - timedelta(days=30), end=today), "last 30 days"
    raise ToolError(f"invalid period '{period}'. Valid: {sorted(VALID_PERIODS)}")


def _parse_platforms(raw: list[str] | None, registry: ConnectorRegistry) -> list[Platform]:
    if not raw:
        return registry.available()
    out: list[Platform] = []
    for p in raw:
        try:
            out.append(Platform(p.lower()))
        except ValueError as e:
            raise ToolError(f"invalid platform '{p}'. Valid: google, yandex") from e
    return out


# ---------------- tools ----------------


async def get_performance_summary(
    registry: ConnectorRegistry,
    platforms: list[str] | None = None,
    period: str = "yesterday",
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    """Combined performance summary across platforms."""
    date_range, label = parse_period(period, date_from, date_to)
    platform_list = _parse_platforms(platforms, registry)
    result: dict[str, Any] = {"period": label, "platforms": {}}
    for platform in platform_list:
        connector = registry.get(platform)
        campaigns = await connector.get_campaigns(date_range)
        totals = {
            "impressions": sum(c.metrics.impressions for c in campaigns),
            "clicks": sum(c.metrics.clicks for c in campaigns),
            "cost_minor": sum(c.metrics.cost_minor for c in campaigns),
            "conversions": sum(c.metrics.conversions for c in campaigns),
            "currency": campaigns[0].currency if campaigns else connector.currency,
        }
        totals["cost"] = round(totals["cost_minor"] / 1_000_000, 2)
        totals["active_campaigns"] = sum(1 for c in campaigns if c.metrics.cost_minor > 0)
        result["platforms"][platform.value] = {
            "totals": totals,
            "campaigns": [_campaign_dict(c) for c in campaigns[:20]],
        }
    return result


async def get_search_queries(
    registry: ConnectorRegistry,
    cfg: Config,
    platform: str,
    period: str = "last_7_days",
    min_impressions: int = 5,
    classify: bool = False,
    limit: int = 200,
) -> dict[str, Any]:
    """Search queries with optional rule-based classification."""
    date_range, label = parse_period(period, None, None)
    plat = Platform(platform.lower())
    connector = registry.get(plat)
    queries = await connector.get_search_queries(
        date_range, min_impressions=min_impressions
    )
    queries.sort(key=lambda q: -q.metrics.cost_minor)
    queries = queries[:limit]
    out: dict[str, Any] = {
        "platform": plat.value,
        "period": label,
        "count": len(queries),
        "queries": [_query_dict(q) for q in queries],
    }
    if classify:
        rules = RuleBasedQueryFilter(
            custom_patterns=cfg.negative_keywords.custom_patterns,
            min_impressions=min_impressions,
        )
        suggestions = rules.classify(queries)
        out["rule_flagged"] = [_suggestion_dict(s) for s in suggestions]
    return out


async def get_negative_suggestions(
    registry: ConnectorRegistry,
    cfg: Config,
    platform: str,
    period: str = "last_30_days",
    min_spend: float = 10.0,
) -> dict[str, Any]:
    """Rule-based negative keyword suggestions ranked by wasted spend."""
    date_range, label = parse_period(period, None, None)
    plat = Platform(platform.lower())
    connector = registry.get(plat)
    queries = await connector.get_search_queries(
        date_range,
        min_impressions=cfg.rules.search_queries.min_impressions_for_review,
    )
    rules = RuleBasedQueryFilter(
        custom_patterns=cfg.negative_keywords.custom_patterns,
        min_impressions=cfg.rules.search_queries.min_impressions_for_review,
    )
    suggestions = rules.classify(queries)
    min_spend_minor = int(min_spend * 1_000_000)
    suggestions = [s for s in suggestions if s.cost_minor >= min_spend_minor]
    return {
        "platform": plat.value,
        "period": label,
        "count": len(suggestions),
        "suggestions": [_suggestion_dict(s) for s in suggestions],
    }


async def apply_negatives(
    registry: ConnectorRegistry,
    platform: str,
    negatives: list[dict[str, Any]],
    dry_run: bool = True,
) -> dict[str, Any]:
    """Apply negative keywords. Dry-run by default for safety."""
    plat = Platform(platform.lower())
    connector = registry.get(plat)
    items: list[NegativeKeyword] = []
    for n in negatives:
        try:
            match = MatchType(n.get("match_type", "phrase").lower())
        except ValueError as e:
            raise ToolError(
                f"invalid match_type in {n}. Valid: exact, phrase, broad"
            ) from e
        items.append(
            NegativeKeyword(
                text=str(n["keyword"]),
                match_type=match,
                level=str(n.get("level", "campaign")),
                campaign_id=n.get("campaign_id"),
                adgroup_id=n.get("adgroup_id"),
                reason=n.get("reason"),
            )
        )
    results = await connector.add_negative_keywords(items, dry_run=dry_run)
    applied = sum(1 for r in results if r.success)
    failed = sum(1 for r in results if not r.success)
    return {
        "platform": plat.value,
        "dry_run": dry_run,
        "applied": applied,
        "failed": failed,
        "results": [
            {
                "success": r.success,
                "resource_name": r.resource_name,
                "error": r.error,
            }
            for r in results
        ],
    }


async def get_campaign_structure(
    registry: ConnectorRegistry,
    platform: str,
) -> dict[str, Any]:
    """Full campaign/adgroup/keyword hierarchy."""
    plat = Platform(platform.lower())
    connector = registry.get(plat)
    tree = await connector.get_campaign_structure()
    return {
        "platform": tree.platform.value,
        "account_id": tree.account_id,
        "currency": tree.currency,
        "campaigns": [
            {
                "id": c.id,
                "name": c.name,
                "status": c.status.value,
                "daily_budget": (
                    c.daily_budget_minor / 1_000_000
                    if c.daily_budget_minor else None
                ),
                "bidding_strategy": c.bidding_strategy,
                "adgroups": [
                    {
                        "id": ag.id,
                        "name": ag.name,
                        "status": ag.status.value,
                        "keywords_count": len(ag.keywords),
                        "ads_count": ag.ads_count,
                    }
                    for ag in c.adgroups
                ],
            }
            for c in tree.campaigns
        ],
    }


async def get_alerts(
    registry: ConnectorRegistry,
    cfg: Config,
    platforms: list[str] | None = None,
    period: str = "last_7_days",
    snapshot_db: str | None = None,
) -> dict[str, Any]:
    """Run spend + performance analyzers and return alerts by severity."""
    date_range, label = parse_period(period, None, None)
    platform_list = _parse_platforms(platforms, registry)
    days = (date_range.end - date_range.start).days + 1
    prior = DateRange(
        start=date_range.start - timedelta(days=days),
        end=date_range.start - timedelta(days=1),
    )
    store = SnapshotStore(snapshot_db) if snapshot_db else None

    all_alerts = []
    for platform in platform_list:
        connector = registry.get(platform)
        campaigns = await connector.get_campaigns(date_range)
        all_alerts.extend(check_spend(campaigns, cfg.rules.spend, days_in_period=days))
        if store is not None:
            store.write(connector.account_id, date.today(), campaigns)
            prior_metrics = store.aggregate(
                platform, connector.account_id, prior.start, prior.end
            )
            if prior_metrics:
                all_alerts.extend(
                    detect_anomalies(campaigns, prior_metrics, cfg.rules.performance)
                )
    all_alerts.sort(key=lambda a: a.sort_key())
    return {
        "period": label,
        "count": len(all_alerts),
        "alerts": [_alert_dict(a) for a in all_alerts],
    }


async def get_spend_pacing(
    registry: ConnectorRegistry,
    platforms: list[str] | None = None,
) -> dict[str, Any]:
    """Today's spend vs daily budget for active campaigns."""
    today = date.today()
    date_range = DateRange(start=today, end=today)
    platform_list = _parse_platforms(platforms, registry)
    out: dict[str, Any] = {"date": today.isoformat(), "platforms": {}}
    for platform in platform_list:
        connector = registry.get(platform)
        campaigns = await connector.get_campaigns(date_range)
        pacing_rows = []
        for c in campaigns:
            pct = (
                c.metrics.cost_minor / c.daily_budget_minor
                if c.daily_budget_minor else None
            )
            pacing_rows.append(
                {
                    "campaign_id": c.id,
                    "campaign_name": c.name,
                    "spent": c.metrics.cost_minor / 1_000_000,
                    "daily_budget": (
                        c.daily_budget_minor / 1_000_000
                        if c.daily_budget_minor else None
                    ),
                    "pct_of_budget": round(pct, 3) if pct is not None else None,
                    "currency": c.currency,
                }
            )
        out["platforms"][platform.value] = {
            "campaigns": pacing_rows,
            "total_spent": sum(
                c.metrics.cost_minor for c in campaigns
            ) / 1_000_000,
        }
    return out


async def compare_platforms(
    registry: ConnectorRegistry,
    metric: str = "cpc",
    period: str = "last_30_days",
) -> dict[str, Any]:
    """Compare Google vs Yandex on a single metric."""
    valid = {"cpc", "cpa", "ctr", "roas", "conversions", "cost"}
    metric = metric.lower()
    if metric not in valid:
        raise ToolError(f"invalid metric '{metric}'. Valid: {sorted(valid)}")
    date_range, label = parse_period(period, None, None)
    platform_list = registry.available()

    rows: dict[str, Any] = {}
    for platform in platform_list:
        connector = registry.get(platform)
        campaigns = await connector.get_campaigns(date_range)
        total_impressions = sum(c.metrics.impressions for c in campaigns)
        total_clicks = sum(c.metrics.clicks for c in campaigns)
        total_cost_minor = sum(c.metrics.cost_minor for c in campaigns)
        total_conv = sum(c.metrics.conversions for c in campaigns)
        total_conv_value = sum(c.metrics.conversion_value_minor for c in campaigns)
        currency = campaigns[0].currency if campaigns else connector.currency

        value: float | None
        if metric == "cpc":
            value = (total_cost_minor / 1_000_000) / total_clicks if total_clicks else None
        elif metric == "cpa":
            value = (total_cost_minor / 1_000_000) / total_conv if total_conv else None
        elif metric == "ctr":
            value = total_clicks / total_impressions if total_impressions else None
        elif metric == "roas":
            value = total_conv_value / total_cost_minor if total_cost_minor else None
        elif metric == "conversions":
            value = total_conv
        else:  # cost
            value = total_cost_minor / 1_000_000

        rows[platform.value] = {
            "value": round(value, 4) if value is not None else None,
            "currency": currency,
            "sample_size_clicks": total_clicks,
            "sample_size_impressions": total_impressions,
        }

    # Currency mismatch guard — don't compare values across currencies
    currencies = {r["currency"] for r in rows.values() if r["value"] is not None}
    return {
        "metric": metric,
        "period": label,
        "platforms": rows,
        "comparable": len(currencies) <= 1,
        "note": (
            None if len(currencies) <= 1
            else "values are in different currencies and should not be compared directly"
        ),
    }


# ---------------- serializers ----------------


def _campaign_dict(c: Any) -> dict[str, Any]:
    return {
        "id": c.id,
        "name": c.name,
        "status": c.status.value,
        "daily_budget": (
            c.daily_budget_minor / 1_000_000 if c.daily_budget_minor else None
        ),
        "cost": round(c.metrics.cost_minor / 1_000_000, 2),
        "impressions": c.metrics.impressions,
        "clicks": c.metrics.clicks,
        "conversions": c.metrics.conversions,
        "ctr": round(c.metrics.ctr, 4),
        "cpc": round(c.metrics.cpc_minor / 1_000_000, 2) if c.metrics.clicks else None,
        "currency": c.currency,
    }


def _query_dict(q: Any) -> dict[str, Any]:
    return {
        "query": q.query,
        "campaign": q.campaign_name,
        "adgroup": q.adgroup_name,
        "impressions": q.metrics.impressions,
        "clicks": q.metrics.clicks,
        "cost": round(q.metrics.cost_minor / 1_000_000, 2),
        "conversions": q.metrics.conversions,
    }


def _suggestion_dict(s: Any) -> dict[str, Any]:
    return {
        "query": s.query,
        "match_type": s.match_type.value,
        "level": s.level,
        "campaign_id": s.campaign_id,
        "adgroup_id": s.adgroup_id,
        "reason": s.reason,
        "category": s.category,
        "source": s.source,
        "confidence": s.confidence,
        "cost": round(s.cost_minor / 1_000_000, 2),
        "clicks": s.clicks,
    }


def _alert_dict(a: Any) -> dict[str, Any]:
    return {
        "severity": a.severity.value,
        "category": a.category,
        "platform": a.platform.value if a.platform else None,
        "title": a.title,
        "detail": a.detail,
        "campaign_id": a.campaign_id,
        "campaign_name": a.campaign_name,
    }
