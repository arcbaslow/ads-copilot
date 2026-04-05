"""Click CLI entrypoint."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from pathlib import Path

import click

from ads_copilot import __version__
from ads_copilot.config import Config, load_config
from ads_copilot.models import DateRange, Platform

log = logging.getLogger(__name__)

DEFAULT_CONFIG = "config.yaml"


def _parse_period(period: str) -> DateRange:
    today = date.today()
    if period == "today":
        return DateRange(start=today, end=today)
    if period == "yesterday":
        y = today - timedelta(days=1)
        return DateRange(start=y, end=y)
    if period.endswith("d"):
        try:
            days = int(period[:-1])
        except ValueError as e:
            raise click.BadParameter(f"invalid period: {period}") from e
        return DateRange(start=today - timedelta(days=days), end=today)
    raise click.BadParameter(
        f"unknown period '{period}'. Try: today, yesterday, 7d, 30d"
    )


def _load(config_path: str) -> Config:
    return load_config(config_path)


def _format_money(minor: int, currency: str) -> str:
    factor = 1_000_000
    return f"{minor / factor:,.2f} {currency}"


@click.group()
@click.version_option(version=__version__, prog_name="ads-copilot")
@click.option(
    "-v", "--verbose", count=True, help="-v for INFO, -vv for DEBUG"
)
@click.pass_context
def main(ctx: click.Context, verbose: int) -> None:
    """ads-copilot: dual-platform campaign auditor."""
    level = logging.WARNING
    if verbose == 1:
        level = logging.INFO
    elif verbose >= 2:
        level = logging.DEBUG
    logging.basicConfig(
        level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    ctx.ensure_object(dict)


@main.command()
@click.option("--config", "-c", default=DEFAULT_CONFIG, help="Path to config.yaml")
@click.option("--google/--no-google", default=True, help="Include Google Ads")
@click.option("--yandex/--no-yandex", default=True, help="Include Yandex Direct")
@click.option("--today", "period_today", is_flag=True, help="Use today's spend")
@click.option("--period", default="today", help="today | yesterday | Nd (e.g. 7d)")
def spend(
    config: str, google: bool, yandex: bool, period_today: bool, period: str
) -> None:
    """Show current spend vs daily budget for active campaigns."""
    cfg = _load(config)
    period_arg = "today" if period_today else period
    date_range = _parse_period(period_arg)

    async def _run() -> int:
        platforms = _select_platforms(google, yandex)
        rows: list[tuple[str, str, str, str, str]] = []
        total_cost_by_currency: dict[str, int] = {}

        for platform in platforms:
            connector = _build_connector(cfg, platform)
            try:
                campaigns = await connector.get_campaigns(date_range)
            finally:
                await connector.close()
            for c in campaigns:
                budget = (
                    _format_money(c.daily_budget_minor, c.currency)
                    if c.daily_budget_minor
                    else "-"
                )
                rows.append(
                    (
                        platform.value,
                        c.name[:40],
                        c.status.value,
                        _format_money(c.metrics.cost_minor, c.currency),
                        budget,
                    )
                )
                total_cost_by_currency[c.currency] = (
                    total_cost_by_currency.get(c.currency, 0) + c.metrics.cost_minor
                )
        _print_table(
            ["Platform", "Campaign", "Status", "Spend", "Daily Budget"], rows
        )
        click.echo("")
        click.echo("Totals:")
        for cur, cost in total_cost_by_currency.items():
            click.echo(f"  {_format_money(cost, cur)}")
        return 0

    raise SystemExit(asyncio.run(_run()))


@main.command()
@click.option("--config", "-c", default=DEFAULT_CONFIG)
@click.option("--google/--no-google", default=True)
@click.option("--yandex/--no-yandex", default=False)
@click.option("--output", "-o", default=None, help="Write markdown to path")
def structure(config: str, google: bool, yandex: bool, output: str | None) -> None:
    """Dump campaign/adgroup hierarchy."""
    cfg = _load(config)

    async def _run() -> int:
        from ads_copilot.reporters.structure_md import render_structure

        platforms = _select_platforms(google, yandex)
        chunks: list[str] = []
        for platform in platforms:
            connector = _build_connector(cfg, platform)
            try:
                tree = await connector.get_campaign_structure()
            finally:
                await connector.close()
            chunks.append(render_structure(tree))
        report = "\n\n".join(chunks)
        if output:
            Path(output).write_text(report, encoding="utf-8")
            click.echo(f"wrote {output}")
        else:
            click.echo(report)
        return 0

    raise SystemExit(asyncio.run(_run()))


@main.command()
@click.option("--config", "-c", default=DEFAULT_CONFIG)
@click.option("--google/--no-google", default=True)
@click.option("--yandex/--no-yandex", default=True)
@click.option("--period", default="30d")
@click.option("--min-impressions", default=5, type=int)
@click.option("--output", "-o", default=None)
def queries(
    config: str,
    google: bool,
    yandex: bool,
    period: str,
    min_impressions: int,
    output: str | None,
) -> None:
    """Pull search-term reports."""
    cfg = _load(config)
    date_range = _parse_period(period)

    async def _run() -> int:
        import csv
        import sys

        platforms = _select_platforms(google, yandex)
        all_rows: list[list[str]] = []
        for platform in platforms:
            connector = _build_connector(cfg, platform)
            try:
                items = await connector.get_search_queries(
                    date_range, min_impressions=min_impressions
                )
            finally:
                await connector.close()
            for q in items:
                all_rows.append(
                    [
                        platform.value,
                        q.query,
                        q.campaign_name,
                        q.adgroup_name,
                        str(q.metrics.impressions),
                        str(q.metrics.clicks),
                        str(q.metrics.cost_minor),
                        f"{q.metrics.conversions:.2f}",
                    ]
                )
        header = [
            "platform",
            "query",
            "campaign",
            "adgroup",
            "impressions",
            "clicks",
            "cost_minor",
            "conversions",
        ]
        if output:
            with Path(output).open("w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(header)
                w.writerows(all_rows)
            click.echo(f"wrote {len(all_rows)} rows to {output}")
        else:
            w = csv.writer(sys.stdout)
            w.writerow(header)
            w.writerows(all_rows)
        return 0

    raise SystemExit(asyncio.run(_run()))


@main.command()
@click.option("--config", "-c", default=DEFAULT_CONFIG)
@click.option("--google/--no-google", default=True)
@click.option("--yandex/--no-yandex", default=True)
@click.option("--period", default="7d")
@click.option("--output", "-o", default=None, help="Write markdown report to path")
@click.option("--telegram", "to_telegram", is_flag=True, help="Send to Telegram")
@click.option(
    "--db",
    default="./ads_copilot.sqlite",
    help="SQLite path for snapshot history",
)
@click.option("--classify/--no-classify", default=False, help="Use AI for search-query classification")
def audit(
    config: str,
    google: bool,
    yandex: bool,
    period: str,
    output: str | None,
    to_telegram: bool,
    db: str,
    classify: bool,
) -> None:
    """Run spend, performance, and query audit checks."""
    cfg = _load(config)
    date_range = _parse_period(period)

    async def _run() -> int:
        from ads_copilot.audit import run_audit
        from ads_copilot.reporters.formatters import format_markdown, format_telegram
        from ads_copilot.storage import SnapshotStore

        platforms = _select_platforms(google, yandex)
        connectors = [_build_connector(cfg, p) for p in platforms]
        store = SnapshotStore(db)
        classifier = None
        if classify:
            if not cfg.ai.enabled:
                raise click.ClickException("ai.enabled is false in config")
            from ads_copilot.ai.query_intent import QueryClassifier

            classifier = QueryClassifier(cfg.ai, cfg.business)
        try:
            report = await run_audit(
                cfg,
                connectors,
                date_range,
                period_label=period,
                store=store,
                classifier=classifier,
            )
            if classifier is not None:
                s = classifier.stats
                click.echo(
                    f"ai: {s.queries_classified}/{s.queries_seen} classified "
                    f"({s.batches} batches, {s.failures} failures, "
                    f"{s.input_tokens + s.output_tokens} tokens)",
                    err=True,
                )
        finally:
            for c in connectors:
                await c.close()

        md = format_markdown(report)
        if output:
            Path(output).write_text(md, encoding="utf-8")
            click.echo(f"wrote {output}")
        else:
            click.echo(md)

        if to_telegram:
            if not cfg.delivery.telegram.enabled:
                raise click.ClickException("delivery.telegram.enabled is false in config")
            from ads_copilot.reporters.telegram import TelegramReporter

            reporter = TelegramReporter.from_env(
                cfg.delivery.telegram.bot_token_env,
                cfg.delivery.telegram.chat_id,
            )
            await reporter.send(format_telegram(report))
            click.echo("telegram: sent")
        return 0

    raise SystemExit(asyncio.run(_run()))


# ---------------- helpers ----------------


def _select_platforms(google: bool, yandex: bool) -> list[Platform]:
    out: list[Platform] = []
    if google:
        out.append(Platform.GOOGLE)
    if yandex:
        out.append(Platform.YANDEX)
    if not out:
        raise click.BadParameter("select at least one platform")
    return out


def _build_connector(cfg: Config, platform: Platform):  # type: ignore[no-untyped-def]
    if platform == Platform.GOOGLE:
        from ads_copilot.connectors.google_ads import (
            GoogleAdsConfig,
            GoogleAdsConnector,
        )

        if not cfg.accounts.google_ads:
            raise click.ClickException("no google_ads accounts configured")
        acct = cfg.accounts.google_ads[0]
        return GoogleAdsConnector(
            GoogleAdsConfig(
                customer_id=acct.customer_id.replace("-", ""),
                credentials_file=acct.credentials_file,
                login_customer_id=acct.login_customer_id,
                currency=acct.currency,
            )
        )
    from ads_copilot.connectors.yandex_direct import (
        YandexConfig,
        YandexDirectConnector,
    )

    if not cfg.accounts.yandex_direct:
        raise click.ClickException("no yandex_direct accounts configured")
    acct = cfg.accounts.yandex_direct[0]
    return YandexDirectConnector(
        YandexConfig(
            token=acct.resolve_token(),
            login=acct.login,
            client_login=acct.client_login,
            sandbox=acct.sandbox,
            currency=acct.currency,
        )
    )


def _print_table(headers: list[str], rows: list[tuple[str, ...]]) -> None:
    if not rows:
        click.echo("(no rows)")
        return
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    line = " | ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    click.echo(line)
    click.echo("-+-".join("-" * w for w in widths))
    for row in rows:
        click.echo(
            " | ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(row))
        )


if __name__ == "__main__":
    main()
