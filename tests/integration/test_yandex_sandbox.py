"""Live tests against api-sandbox.direct.yandex.com.

Gated by YANDEX_SANDBOX_TOKEN and YANDEX_SANDBOX_LOGIN. See
docs/SANDBOX.md for how to obtain credentials.
"""

from __future__ import annotations

import pytest

from ads_copilot.connectors.yandex_direct import YandexConfig, YandexDirectConnector
from ads_copilot.models import DateRange, Platform

pytestmark = pytest.mark.integration


def _build(creds: dict[str, str]) -> YandexDirectConnector:
    return YandexDirectConnector(
        YandexConfig(
            token=creds["token"],
            login=creds["login"],
            sandbox=True,
            currency="RUB",
        )
    )


async def test_sandbox_get_campaigns(
    yandex_sandbox_creds: dict[str, str], last_7_days: DateRange
) -> None:
    conn = _build(yandex_sandbox_creds)
    try:
        campaigns = await conn.get_campaigns(last_7_days)
    finally:
        await conn.close()
    # Sandbox may or may not have campaigns — both are valid outcomes
    assert isinstance(campaigns, list)
    for c in campaigns:
        assert c.platform == Platform.YANDEX
        assert c.id
        assert c.currency


async def test_sandbox_get_campaign_structure(
    yandex_sandbox_creds: dict[str, str],
) -> None:
    conn = _build(yandex_sandbox_creds)
    try:
        tree = await conn.get_campaign_structure()
    finally:
        await conn.close()
    assert tree.platform == Platform.YANDEX
    assert tree.account_id
    assert isinstance(tree.campaigns, list)


async def test_sandbox_get_search_queries(
    yandex_sandbox_creds: dict[str, str], last_30_days: DateRange
) -> None:
    conn = _build(yandex_sandbox_creds)
    try:
        queries = await conn.get_search_queries(last_30_days, min_impressions=1)
    finally:
        await conn.close()
    assert isinstance(queries, list)
    for q in queries:
        assert q.platform == Platform.YANDEX
        assert isinstance(q.query, str)
        assert q.metrics.impressions >= 1


async def test_sandbox_get_adgroups(
    yandex_sandbox_creds: dict[str, str], last_7_days: DateRange
) -> None:
    conn = _build(yandex_sandbox_creds)
    try:
        adgroups = await conn.get_adgroups(campaign_ids=None, period=last_7_days)
    finally:
        await conn.close()
    assert isinstance(adgroups, list)


async def test_sandbox_add_negatives_dry_run(
    yandex_sandbox_creds: dict[str, str],
) -> None:
    """Dry-run should never hit the API — test this path is safe."""
    from ads_copilot.models import MatchType, NegativeKeyword

    conn = _build(yandex_sandbox_creds)
    try:
        results = await conn.add_negative_keywords(
            [
                NegativeKeyword(
                    text="test-negative",
                    match_type=MatchType.PHRASE,
                    level="campaign",
                    campaign_id="1",
                )
            ],
            dry_run=True,
        )
    finally:
        await conn.close()
    assert len(results) == 1
    assert results[0].success
    assert results[0].resource_name and "dry-run" in results[0].resource_name
