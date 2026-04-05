"""SQLite-backed daily snapshot store for period-over-period comparison.

Keeps one row per (platform, account_id, campaign_id, date) and aggregates
on demand.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from ads_copilot.models import CampaignData, Metrics, Platform

SCHEMA = """
CREATE TABLE IF NOT EXISTS campaign_snapshots (
    platform TEXT NOT NULL,
    account_id TEXT NOT NULL,
    campaign_id TEXT NOT NULL,
    campaign_name TEXT NOT NULL,
    snapshot_date TEXT NOT NULL,          -- ISO date (the day the metrics cover)
    impressions INTEGER NOT NULL,
    clicks INTEGER NOT NULL,
    cost_minor INTEGER NOT NULL,
    conversions REAL NOT NULL,
    conversion_value_minor INTEGER NOT NULL,
    currency TEXT NOT NULL,
    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (platform, account_id, campaign_id, snapshot_date)
);

CREATE INDEX IF NOT EXISTS ix_snapshots_date
    ON campaign_snapshots (snapshot_date);
"""


@dataclass(slots=True)
class Snapshot:
    platform: Platform
    account_id: str
    campaign_id: str
    campaign_name: str
    snapshot_date: date
    metrics: Metrics
    currency: str


class SnapshotStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def write(
        self,
        account_id: str,
        snapshot_date: date,
        campaigns: list[CampaignData],
    ) -> int:
        """Upsert daily metrics for each campaign."""
        if not campaigns:
            return 0
        rows = [
            (
                c.platform.value,
                account_id,
                c.id,
                c.name,
                snapshot_date.isoformat(),
                c.metrics.impressions,
                c.metrics.clicks,
                c.metrics.cost_minor,
                c.metrics.conversions,
                c.metrics.conversion_value_minor,
                c.currency,
            )
            for c in campaigns
        ]
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO campaign_snapshots
                  (platform, account_id, campaign_id, campaign_name, snapshot_date,
                   impressions, clicks, cost_minor, conversions,
                   conversion_value_minor, currency)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        return len(rows)

    def aggregate(
        self,
        platform: Platform,
        account_id: str,
        date_from: date,
        date_to: date,
    ) -> dict[str, Metrics]:
        """Sum metrics by campaign_id across the date range (inclusive)."""
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT campaign_id,
                       SUM(impressions), SUM(clicks),
                       SUM(cost_minor), SUM(conversions),
                       SUM(conversion_value_minor)
                FROM campaign_snapshots
                WHERE platform = ?
                  AND account_id = ?
                  AND snapshot_date BETWEEN ? AND ?
                GROUP BY campaign_id
                """,
                (
                    platform.value,
                    account_id,
                    date_from.isoformat(),
                    date_to.isoformat(),
                ),
            )
            result: dict[str, Metrics] = {}
            for cid, imp, clk, cost, conv, cv in cur.fetchall():
                result[cid] = Metrics(
                    impressions=int(imp or 0),
                    clicks=int(clk or 0),
                    cost_minor=int(cost or 0),
                    conversions=float(conv or 0),
                    conversion_value_minor=int(cv or 0),
                )
            return result
