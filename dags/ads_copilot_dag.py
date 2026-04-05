"""Airflow DAG — ads-copilot daily audit.

Drop this file into your Airflow `dags/` folder. Set the required env vars on
the worker (YANDEX_DIRECT_TOKEN, ANTHROPIC_API_KEY if classify=True,
TELEGRAM_BOT_TOKEN if Telegram is enabled) and mount config.yaml at
/opt/ads-copilot/config.yaml, or override ADS_COPILOT_CONFIG.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

DEFAULT_ARGS = {
    "owner": "ads-copilot",
    "depends_on_past": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=15),
}

CONFIG_PATH = os.environ.get("ADS_COPILOT_CONFIG", "/opt/ads-copilot/config.yaml")
DB_PATH = os.environ.get("ADS_COPILOT_DB", "/opt/ads-copilot/ads_copilot.sqlite")
CLASSIFY = os.environ.get("ADS_COPILOT_CLASSIFY", "false").lower() == "true"


def run_daily_audit(**_: object) -> None:
    """Airflow Python callable — runs one audit pass."""
    from ads_copilot.scheduler.job import JobOptions, run_scheduled_audit

    opts = JobOptions(
        config_path=CONFIG_PATH,
        db_path=DB_PATH,
        period_days=1,
        classify=CLASSIFY,
    )
    result = asyncio.run(run_scheduled_audit(opts))
    print(
        f"audit complete: {result.alerts} alerts, "
        f"{result.suggestions} suggestions, "
        f"{result.queries_reviewed} queries, "
        f"delivered={result.delivered}"
    )


with DAG(
    dag_id="ads_copilot_daily_audit",
    description="Daily Google Ads + Yandex Direct audit with Telegram digest",
    default_args=DEFAULT_ARGS,
    schedule="0 8 * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["ads", "marketing", "audit"],
) as dag:
    audit = PythonOperator(
        task_id="run_audit",
        python_callable=run_daily_audit,
    )
