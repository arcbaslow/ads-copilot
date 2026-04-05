"""Shared fixtures for integration tests.

Integration tests are skipped unless the required credential env vars are
set. They hit real sandbox APIs. See docs/SANDBOX.md for setup.
"""

from __future__ import annotations

import os
from datetime import date, timedelta

import pytest

from ads_copilot.models import DateRange

YANDEX_VARS = ("YANDEX_SANDBOX_TOKEN", "YANDEX_SANDBOX_LOGIN")
GOOGLE_VARS = ("GOOGLE_ADS_TEST_CUSTOMER_ID", "GOOGLE_ADS_CREDENTIALS_FILE")


def _missing(vars_: tuple[str, ...]) -> list[str]:
    return [v for v in vars_ if not os.environ.get(v)]


@pytest.fixture
def yandex_sandbox_creds() -> dict[str, str]:
    missing = _missing(YANDEX_VARS)
    if missing:
        pytest.skip(f"missing env vars: {', '.join(missing)}")
    return {
        "token": os.environ["YANDEX_SANDBOX_TOKEN"],
        "login": os.environ["YANDEX_SANDBOX_LOGIN"],
    }


@pytest.fixture
def google_ads_test_creds() -> dict[str, str]:
    missing = _missing(GOOGLE_VARS)
    if missing:
        pytest.skip(f"missing env vars: {', '.join(missing)}")
    return {
        "customer_id": os.environ["GOOGLE_ADS_TEST_CUSTOMER_ID"].replace("-", ""),
        "credentials_file": os.environ["GOOGLE_ADS_CREDENTIALS_FILE"],
    }


@pytest.fixture
def last_7_days() -> DateRange:
    today = date.today()
    return DateRange(start=today - timedelta(days=7), end=today)


@pytest.fixture
def last_30_days() -> DateRange:
    today = date.today()
    return DateRange(start=today - timedelta(days=30), end=today)
