"""Per-account audit runner.

Used by both the APScheduler daemon and the Airflow DAG. Iterates every
configured account (agency mode), runs a dedicated audit, and delivers to
whichever channels are enabled. Each account produces its own markdown
file, Telegram message, Slack post, or email.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from ads_copilot.audit import run_audit
from ads_copilot.config import Config, load_config
from ads_copilot.connectors.base import AdPlatformConnector
from ads_copilot.models import DateRange
from ads_copilot.reporters.formatters import (
    AuditReport,
    format_markdown,
    format_telegram,
)
from ads_copilot.storage import SnapshotStore

log = logging.getLogger(__name__)


@dataclass(slots=True)
class AccountResult:
    account: str
    alerts: int
    suggestions: int
    queries_reviewed: int
    delivered: list[str]


@dataclass(slots=True)
class JobResult:
    accounts: list[AccountResult] = field(default_factory=list)

    @property
    def total_alerts(self) -> int:
        return sum(a.alerts for a in self.accounts)

    @property
    def total_suggestions(self) -> int:
        return sum(a.suggestions for a in self.accounts)


@dataclass(slots=True)
class JobOptions:
    config_path: str
    db_path: str = "./ads_copilot.sqlite"
    period_days: int = 1
    classify: bool = False
    report_dir: str = "./reports"


async def run_scheduled_audit(options: JobOptions) -> JobResult:
    """Run one audit pass per configured account and deliver results."""
    cfg = load_config(options.config_path)

    end = date.today()
    start = end - timedelta(days=options.period_days - 1)
    period = DateRange(start=start, end=end)
    label = "today" if options.period_days == 1 else f"last {options.period_days}d"

    classifier = _build_classifier(cfg) if options.classify and cfg.ai.enabled else None
    store = SnapshotStore(options.db_path)
    accounts = _enumerate_accounts(cfg)

    result = JobResult()
    if not accounts:
        log.warning("no accounts configured — nothing to do")
        return result

    for account_name, connector in accounts:
        log.info("running audit for account %r", account_name)
        try:
            report = await run_audit(
                cfg, [connector], period,
                period_label=label, store=store, classifier=classifier,
                account_label=account_name,
            )
        finally:
            try:
                await connector.close()
            except Exception as e:
                log.warning("connector close failed: %s", e)

        delivered = await _deliver(cfg, report, account_name, options.report_dir)
        result.accounts.append(
            AccountResult(
                account=account_name,
                alerts=len(report.alerts),
                suggestions=len(report.negative_suggestions),
                queries_reviewed=report.queries_reviewed,
                delivered=delivered,
            )
        )
    return result


def _enumerate_accounts(cfg: Config) -> list[tuple[str, AdPlatformConnector]]:
    """Build one (account_name, connector) per configured account."""
    out: list[tuple[str, AdPlatformConnector]] = []
    for g in cfg.accounts.google_ads:
        from ads_copilot.connectors.google_ads import (
            GoogleAdsConfig,
            GoogleAdsConnector,
        )
        out.append(
            (
                f"{g.name} (Google)",
                GoogleAdsConnector(
                    GoogleAdsConfig(
                        customer_id=g.customer_id.replace("-", ""),
                        credentials_file=g.credentials_file,
                        login_customer_id=g.login_customer_id,
                        currency=g.currency,
                    )
                ),
            )
        )
    for y in cfg.accounts.yandex_direct:
        from ads_copilot.connectors.yandex_direct import (
            YandexConfig,
            YandexDirectConnector,
        )
        out.append(
            (
                f"{y.name} (Yandex)",
                YandexDirectConnector(
                    YandexConfig(
                        token=y.resolve_token(),
                        login=y.login,
                        client_login=y.client_login,
                        sandbox=y.sandbox,
                        currency=y.currency,
                    )
                ),
            )
        )
    return out


def _build_classifier(cfg: Config):  # type: ignore[no-untyped-def]
    from ads_copilot.ai.query_intent import QueryClassifier
    return QueryClassifier(cfg.ai, cfg.business)


async def _deliver(
    cfg: Config,
    report: AuditReport,
    account_name: str,
    output_dir: str,
) -> list[str]:
    delivered: list[str] = []
    slug = _slugify(account_name)

    if cfg.delivery.markdown.enabled:
        out_dir = Path(cfg.delivery.markdown.output_dir or output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"audit-{report.report_date.isoformat()}-{slug}.md"
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
            log.info("sent Telegram report for %s", account_name)
            delivered.append("telegram")
        except Exception as e:
            log.error("telegram delivery failed: %s", e)

    if cfg.delivery.slack.enabled:
        try:
            from ads_copilot.reporters.slack import SlackReporter

            reporter = SlackReporter.from_env(cfg.delivery.slack.webhook_url_env)
            await reporter.send(report)
            log.info("sent Slack report for %s", account_name)
            delivered.append("slack")
        except Exception as e:
            log.error("slack delivery failed: %s", e)

    if cfg.delivery.email.enabled:
        try:
            from ads_copilot.reporters.email import EmailReporter

            reporter = EmailReporter.from_config(
                smtp_host=cfg.delivery.email.smtp_host,
                smtp_port=cfg.delivery.email.smtp_port,
                smtp_user_env=cfg.delivery.email.smtp_user_env,
                smtp_password_env=cfg.delivery.email.smtp_password_env,
                from_addr=cfg.delivery.email.from_addr,
                to=cfg.delivery.email.to,
            )
            await reporter.send(report)
            log.info("sent email report for %s", account_name)
            delivered.append("email")
        except Exception as e:
            log.error("email delivery failed: %s", e)

    return delivered


def _slugify(text: str) -> str:
    allowed = "abcdefghijklmnopqrstuvwxyz0123456789-"
    s = text.lower().replace(" ", "-").replace("(", "").replace(")", "")
    return "".join(c for c in s if c in allowed).strip("-") or "account"


__all__ = ["AccountResult", "JobOptions", "JobResult", "run_scheduled_audit"]
