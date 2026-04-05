"""APScheduler daemon. Reads cron expression from config and runs
run_scheduled_audit on schedule. Single process, no external broker needed.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from datetime import datetime
from typing import Any

from ads_copilot.config import Config, load_config
from ads_copilot.scheduler.job import JobOptions, run_scheduled_audit

log = logging.getLogger(__name__)


def parse_cron(expression: str) -> dict[str, str]:
    """Parse a 5-field cron expression into APScheduler kwargs.

    Format: minute hour day month day_of_week
    """
    parts = expression.strip().split()
    if len(parts) != 5:
        raise ValueError(
            f"cron expression must have 5 fields (got {len(parts)}): {expression!r}"
        )
    return {
        "minute": parts[0],
        "hour": parts[1],
        "day": parts[2],
        "month": parts[3],
        "day_of_week": parts[4],
    }


class CronDaemon:
    """Thin wrapper around AsyncIOScheduler. Owns the event loop."""

    def __init__(self, config_path: str, db_path: str, classify: bool) -> None:
        self.config_path = config_path
        self.db_path = db_path
        self.classify = classify
        self._cfg: Config | None = None
        self._stopping = False

    def _load(self) -> Config:
        if self._cfg is None:
            self._cfg = load_config(self.config_path)
        return self._cfg

    async def _job(self) -> None:
        log.info("cron job fired at %s", datetime.now().isoformat())
        try:
            result = await run_scheduled_audit(
                JobOptions(
                    config_path=self.config_path,
                    db_path=self.db_path,
                    classify=self.classify,
                )
            )
            log.info(
                "audit complete: %d alerts, %d suggestions, %d queries reviewed, "
                "delivered=%s",
                result.alerts, result.suggestions,
                result.queries_reviewed, result.delivered,
            )
        except Exception:
            log.exception("audit job failed")

    async def run(self) -> None:
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
            from apscheduler.triggers.cron import CronTrigger
        except ImportError as e:
            raise RuntimeError(
                "apscheduler is not installed. `pip install apscheduler`."
            ) from e

        cfg = self._load()
        if not cfg.schedule.enabled:
            raise RuntimeError("schedule.enabled is false in config — nothing to run")

        cron_kwargs = parse_cron(cfg.schedule.cron)
        trigger = CronTrigger(timezone=cfg.schedule.timezone, **cron_kwargs)

        scheduler: Any = AsyncIOScheduler()
        scheduler.add_job(self._job, trigger=trigger, name="ads-copilot-audit")
        scheduler.start()

        log.info(
            "scheduler started: cron=%r tz=%s",
            cfg.schedule.cron, cfg.schedule.timezone,
        )
        next_run = scheduler.get_jobs()[0].next_run_time
        log.info("next run: %s", next_run)

        loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()

        def _request_stop(*_: Any) -> None:
            self._stopping = True
            stop_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _request_stop)
            except NotImplementedError:
                # Windows doesn't support add_signal_handler; rely on KeyboardInterrupt
                pass

        try:
            await stop_event.wait()
        finally:
            log.info("shutting down scheduler")
            scheduler.shutdown(wait=False)
