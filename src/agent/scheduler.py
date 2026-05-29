"""APScheduler entry point — daily-close cadence (resolved decision).

Runs one evaluation cycle shortly after the US market close on trading weekdays.
No 30-min intraday loop. On a laptop that sleeps, a missed run needs no backfill:
the next run simply re-evaluates against the latest daily candles.
"""

from __future__ import annotations

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from src.agent import jobs
from src.core.config import settings


def run_scheduled() -> None:
    """Start the blocking scheduler (Ctrl-C to stop)."""
    scheduler = BlockingScheduler(timezone=settings.market_tz)
    trigger = CronTrigger(
        day_of_week="mon-fri",
        hour=settings.eod_eval_hour,
        minute=settings.eod_eval_minute,
        timezone=settings.market_tz,
    )
    scheduler.add_job(
        jobs.run_once,
        trigger=trigger,
        id="daily_close_eval",
        name="Daily-close signal evaluation",
        misfire_grace_time=3600,  # tolerate up to 1h late (laptop waking, etc.)
        coalesce=True,
    )
    logger.info(
        "Agent started — daily-close eval at {:02d}:{:02d} {} (Mon-Fri). Ctrl-C to stop.",
        settings.eod_eval_hour,
        settings.eod_eval_minute,
        settings.market_tz,
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Agent stopped.")
