#!/usr/bin/env python
"""Manual smoke test: exercise every connector method and print results.

Reads credentials from environment variables. Use this before cutting a
release or after changing connector code. See docs/SANDBOX.md for setup.

Usage:
    python scripts/smoke.py yandex
    python scripts/smoke.py google
    python scripts/smoke.py both
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import date, timedelta
from typing import Any

from ads_copilot.models import DateRange, Platform


def _fmt_money(minor: int, currency: str) -> str:
    return f"{minor / 1_000_000:,.2f} {currency}"


def _header(text: str) -> None:
    print(f"\n{'=' * 60}\n{text}\n{'=' * 60}")


def _section(text: str) -> None:
    print(f"\n-- {text} --")


async def _smoke_yandex() -> None:
    from ads_copilot.connectors.yandex_direct import (
        YandexConfig,
        YandexDirectConnector,
    )

    token = os.environ.get("YANDEX_SANDBOX_TOKEN")
    login = os.environ.get("YANDEX_SANDBOX_LOGIN")
    if not token or not login:
        print("SKIP yandex: YANDEX_SANDBOX_TOKEN / YANDEX_SANDBOX_LOGIN not set")
        return

    _header(f"Yandex Direct sandbox — login={login}")
    today = date.today()
    period = DateRange(start=today - timedelta(days=7), end=today)
    month = DateRange(start=today - timedelta(days=30), end=today)

    conn = YandexDirectConnector(
        YandexConfig(token=token, login=login, sandbox=True, currency="RUB")
    )
    try:
        _section("get_campaigns(last_7_days)")
        campaigns = await conn.get_campaigns(period)
        print(f"  {len(campaigns)} campaigns")
        for c in campaigns[:5]:
            print(
                f"    [{c.status.value}] {c.name}: "
                f"{_fmt_money(c.metrics.cost_minor, c.currency)} spent, "
                f"{c.metrics.clicks} clicks"
            )

        _section("get_campaign_structure()")
        tree = await conn.get_campaign_structure()
        print(f"  account={tree.account_id} currency={tree.currency}")
        for c in tree.campaigns[:5]:
            print(f"    - {c.name} ({len(c.adgroups)} adgroups)")

        _section("get_adgroups(all campaigns, last_7_days)")
        adgroups = await conn.get_adgroups(None, period)
        print(f"  {len(adgroups)} adgroups")

        _section("get_search_queries(last_30_days, min_impr=1)")
        queries = await conn.get_search_queries(month, min_impressions=1)
        print(f"  {len(queries)} queries")
        for q in queries[:5]:
            print(
                f"    {q.query!r} — {q.metrics.impressions} impr, "
                f"{q.metrics.clicks} clk, "
                f"{_fmt_money(q.metrics.cost_minor, 'RUB')}"
            )
    finally:
        await conn.close()


async def _smoke_google() -> None:
    from ads_copilot.connectors.google_ads import GoogleAdsConfig, GoogleAdsConnector

    customer_id = os.environ.get("GOOGLE_ADS_TEST_CUSTOMER_ID")
    creds_file = os.environ.get("GOOGLE_ADS_CREDENTIALS_FILE")
    if not customer_id or not creds_file:
        print(
            "SKIP google: GOOGLE_ADS_TEST_CUSTOMER_ID / "
            "GOOGLE_ADS_CREDENTIALS_FILE not set"
        )
        return

    _header(f"Google Ads test account — customer={customer_id}")
    today = date.today()
    period = DateRange(start=today - timedelta(days=7), end=today)

    conn = GoogleAdsConnector(
        GoogleAdsConfig(
            customer_id=customer_id.replace("-", ""),
            credentials_file=creds_file,
            currency="USD",
        )
    )
    try:
        _section("get_campaigns(last_7_days)")
        campaigns = await conn.get_campaigns(period)
        print(f"  {len(campaigns)} campaigns")
        for c in campaigns[:5]:
            print(
                f"    [{c.status.value}] {c.name}: "
                f"{_fmt_money(c.metrics.cost_minor, c.currency)} spent"
            )

        _section("get_campaign_structure()")
        tree = await conn.get_campaign_structure()
        print(f"  account={tree.account_id} campaigns={len(tree.campaigns)}")
        for c in tree.campaigns[:3]:
            print(f"    - {c.name} ({len(c.adgroups)} adgroups)")
            for ag in c.adgroups[:3]:
                print(f"        └── {ag.name} ({len(ag.keywords)} kw, {ag.ads_count} ads)")

        _section("get_search_queries(last_7_days, min_impr=1)")
        queries = await conn.get_search_queries(period, min_impressions=1)
        print(f"  {len(queries)} queries")
    finally:
        await conn.close()


async def _main(targets: list[str]) -> int:
    if "yandex" in targets or "both" in targets:
        try:
            await _smoke_yandex()
        except Exception as e:
            print(f"FAIL yandex: {type(e).__name__}: {e}")
            return 1
    if "google" in targets or "both" in targets:
        try:
            await _smoke_google()
        except Exception as e:
            print(f"FAIL google: {type(e).__name__}: {e}")
            return 1
    print("\nOK")
    return 0


def main() -> None:
    targets = sys.argv[1:] or ["both"]
    sys.exit(asyncio.run(_main(targets)))


if __name__ == "__main__":
    main()


# keep Any import warning-free
_ = Any
_ = Platform
