"""Live tests against a Google Ads test account.

Gated by GOOGLE_ADS_TEST_CUSTOMER_ID and GOOGLE_ADS_CREDENTIALS_FILE. Test
accounts use the production API endpoint but a test-customer-id, so you
get real API behavior without affecting real campaigns. See
docs/SANDBOX.md for setup.
"""

from __future__ import annotations

import pytest

from ads_copilot.connectors.google_ads import GoogleAdsConfig, GoogleAdsConnector
from ads_copilot.models import DateRange, Platform

pytestmark = pytest.mark.integration


def _build(creds: dict[str, str]) -> GoogleAdsConnector:
    return GoogleAdsConnector(
        GoogleAdsConfig(
            customer_id=creds["customer_id"],
            credentials_file=creds["credentials_file"],
            currency="USD",
        )
    )


async def test_sandbox_get_campaigns(
    google_ads_test_creds: dict[str, str], last_7_days: DateRange
) -> None:
    conn = _build(google_ads_test_creds)
    try:
        campaigns = await conn.get_campaigns(last_7_days)
    finally:
        await conn.close()
    assert isinstance(campaigns, list)
    for c in campaigns:
        assert c.platform == Platform.GOOGLE
        assert c.id
        assert c.status


async def test_sandbox_get_campaign_structure(
    google_ads_test_creds: dict[str, str],
) -> None:
    conn = _build(google_ads_test_creds)
    try:
        tree = await conn.get_campaign_structure()
    finally:
        await conn.close()
    assert tree.platform == Platform.GOOGLE
    assert tree.account_id


async def test_sandbox_get_search_queries(
    google_ads_test_creds: dict[str, str], last_30_days: DateRange
) -> None:
    conn = _build(google_ads_test_creds)
    try:
        queries = await conn.get_search_queries(last_30_days, min_impressions=1)
    finally:
        await conn.close()
    assert isinstance(queries, list)


async def test_sandbox_get_adgroups(
    google_ads_test_creds: dict[str, str], last_7_days: DateRange
) -> None:
    conn = _build(google_ads_test_creds)
    try:
        adgroups = await conn.get_adgroups(None, last_7_days)
    finally:
        await conn.close()
    assert isinstance(adgroups, list)
