from datetime import date, timedelta
from pathlib import Path

from ads_copilot.models import CampaignData, CampaignStatus, Metrics, Platform
from ads_copilot.storage import SnapshotStore


def _c(cid: str, cost: int, clicks: int = 10, impressions: int = 500) -> CampaignData:
    return CampaignData(
        platform=Platform.GOOGLE,
        id=cid,
        name=f"C{cid}",
        status=CampaignStatus.ENABLED,
        daily_budget_minor=None,
        bidding_strategy=None,
        metrics=Metrics(impressions=impressions, clicks=clicks, cost_minor=cost),
        currency="USD",
    )


def test_write_and_aggregate(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "s.sqlite")
    today = date(2026, 4, 5)
    yesterday = today - timedelta(days=1)

    store.write("acct", today, [_c("1", 50_000_000, clicks=10)])
    store.write("acct", yesterday, [_c("1", 30_000_000, clicks=6)])

    agg = store.aggregate(Platform.GOOGLE, "acct", yesterday, today)
    assert "1" in agg
    assert agg["1"].cost_minor == 80_000_000
    assert agg["1"].clicks == 16


def test_upsert_same_day(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "s.sqlite")
    today = date(2026, 4, 5)
    store.write("acct", today, [_c("1", 50_000_000)])
    store.write("acct", today, [_c("1", 75_000_000)])  # re-run, should overwrite
    agg = store.aggregate(Platform.GOOGLE, "acct", today, today)
    assert agg["1"].cost_minor == 75_000_000


def test_aggregate_empty(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "s.sqlite")
    assert store.aggregate(Platform.GOOGLE, "acct", date(2026, 1, 1), date(2026, 1, 2)) == {}


def test_platform_isolation(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "s.sqlite")
    today = date(2026, 4, 5)
    g = _c("1", 10_000_000)
    y = CampaignData(
        platform=Platform.YANDEX,
        id="1",
        name="Y",
        status=CampaignStatus.ENABLED,
        daily_budget_minor=None,
        bidding_strategy=None,
        metrics=Metrics(impressions=100, clicks=5, cost_minor=20_000_000),
        currency="RUB",
    )
    store.write("acct", today, [g, y])
    google = store.aggregate(Platform.GOOGLE, "acct", today, today)
    yandex = store.aggregate(Platform.YANDEX, "acct", today, today)
    assert google["1"].cost_minor == 10_000_000
    assert yandex["1"].cost_minor == 20_000_000
