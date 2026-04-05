"""One-shot audit job. Used by the APScheduler daemon and Airflow DAG alike.

Each invocation: load config, build connectors, run audit, deliver to
whichever channels are enabled. Reads nothing from a live loop — safe to
call from any scheduler.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from ads_copilot.audit import run_audit
from ads_copilot.config import Config, load_config
from ads_copilot.connectors.base import AdPlatformConnector
from ads_copilot.models import DateRange, Platform
from ads_copilot.reporters.formatters import format_markdown, format_telegram
from ads_copilot.storage import SnapshotStore

log = logging.getLogger(__name__)


@dataclass(slots=True)
class JobResult:
    alerts: int
    suggestions: int
    queries_reviewed: int
    delivered: list[str]  # channels that accepted the report


@dataclass(slots=True)
class JobOptions:
    config_path: str
    db_path: str = "./ads_copilot.sqlite"
    period_days: int = 1
    classify: bool = False
    report_dir: str = "./reports"


async def run_scheduled_audit(options: JobOptions) -> JobResult:
    """Run one audit pass and deliver results. Return summary."""
    cfg = load_config(options.config_path)

    end = date.today()
    start = end - timedelta(days=options.period_days - 1)
    period = DateRange(start=start, end=end)
    label = "today" if options.period_days == 1 else f"last {options.period_days}d"

    connectors = _build_connectors(cfg)
    if not connectors:
        log.warning("no connectors configured — nothing to do")
        return JobResult(alerts=0, suggestions=0, queries_reviewed=0, delivered=[])

    classifier = _build_classifier(cfg) if options.classify and cfg.ai.enabled else None
    store = SnapshotStore(options.db_path)

    try:
        report = await run_audit(
            cfg, connectors, period,
            period_label=label, store=store, classifier=classifier,
        )
    finally:
        for c in connectors:
            try:
                await c.close()
            except Exception as e:
                log.warning("connector close failed: %s", e)

    delivered = await _deliver(cfg, report, options.report_dir)
    return JobResult(
        alerts=len(report.alerts),
        suggestions=len(report.negative_suggestions),
        queries_reviewed=report.queries_reviewed,
        delivered=delivered,
    )


def _build_connectors(cfg: Config) -> list[AdPlatformConnector]:
    connectors: list[AdPlatformConnector] = []
    for g in cfg.accounts.google_ads:
        from ads_copilot.connectors.google_ads import (
            GoogleAdsConfig, GoogleAdsConnector,
        )
        connectors.append(
            GoogleAdsConnector(
                GoogleAdsConfig(
                    customer_id=g.customer_id.replace("-", ""),
                    credentials_file=g.credentials_file,
                    login_customer_id=g.login_customer_id,
                    currency=g.currency,
                )
            )
        )
    for y in cfg.accounts.yandex_direct:
        from ads_copilot.connectors.yandex_direct import (
            YandexConfig, YandexDirectConnector,
        )
        connectors.append(
            YandexDirectConnector(
                YandexConfig(
                    token=y.resolve_token(),
                    login=y.login,
                    client_login=y.client_login,
                    sandbox=y.sandbox,
                    currency=y.currency,
                )
            )
        )
    return connectors


def _build_classifier(cfg: Config):  # type: ignore[no-untyped-def]
    from ads_copilot.ai.query_intent import QueryClassifier
    return QueryClassifier(cfg.ai, cfg.business)


async def _deliver(cfg: Config, report, output_dir: str) -> list[str]:  # type: ignore[no-untyped-def]
    delivered: list[str] = []

    if cfg.delivery.markdown.enabled:
        out_dir = Path(cfg.delivery.markdown.output_dir or output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"audit-{report.report_date.isoformat()}.md"
        path.write_text(format_markdown(report), encoding="utf-8")
        log.info("wrote markdown report to %s", path)
        delivered.append("markdown")

    if cfg.delivery.telegram.enabled and cfg.delivery.telegram.chat_id:
        try:
            from ads_copilot.reporters.telegram import TelegramReporter

            reporter = TelegramReporter.from_env(
                cfg.delivery.telegram.bot_token_env,
                cfg.delivery.telegram.chat_id,
            )
            await reporter.send(format_telegram(report))
            log.info("sent Telegram report")
            delivered.append("telegram")
        except Exception as e:
            log.error("telegram delivery failed: %s", e)

    return delivered


# Hint for Platform used in delivery tests
__all__ = ["JobOptions", "JobResult", "run_scheduled_audit"]
_ = Platform
