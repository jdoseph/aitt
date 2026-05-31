"""APScheduler entry point — daily-close cadence + the Session 15 paper engine.

Daily-close (~16:15) runs the full signal cycle and queues paper entries/exits.
The autonomous paper engine adds three intraday jobs on trading weekdays:

  * market-open (~9:31): fill PENDING entries + queued/gapped exits,
  * monitor (every ``monitor_interval_minutes`` between the monitor window): stop
    / target surveillance on OPEN positions,
  * daily-summary (~16:30): one end-of-day NAV-vs-VOO notification.

Each job re-checks the trading calendar so nothing fires on a market holiday.
On a laptop that sleeps, a missed run needs no backfill — the next run simply
re-evaluates against the latest data.
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

    # --- daily-close evaluation + paper entry/exit queueing ---
    scheduler.add_job(
        jobs.run_daily_eval,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=settings.eod_eval_hour,
            minute=settings.eod_eval_minute,
            timezone=settings.market_tz,
        ),
        id="daily_close_eval",
        name="Daily-close signal evaluation + paper queueing",
        misfire_grace_time=3600,  # tolerate up to 1h late (laptop waking, etc.)
        coalesce=True,
    )

    if settings.enable_paper_trading:
        open_h, open_m = settings.market_open_hm
        start_h, start_m = settings.monitor_start_hm
        end_h, end_m = settings.monitor_end_hm
        sum_h, sum_m = settings.daily_summary_hm

        scheduler.add_job(
            jobs.run_market_open,
            trigger=CronTrigger(
                day_of_week="mon-fri", hour=open_h, minute=open_m, timezone=settings.market_tz
            ),
            id="market_open_fills",
            name="Market-open paper fills",
            misfire_grace_time=600,
            coalesce=True,
        )
        scheduler.add_job(
            jobs.run_monitor,
            trigger=CronTrigger(
                day_of_week="mon-fri",
                hour=f"{start_h}-{end_h}",
                minute=f"*/{settings.monitor_interval_minutes}",
                timezone=settings.market_tz,
            ),
            id="intraday_monitor",
            name="Intraday stop/target monitor",
            misfire_grace_time=settings.monitor_interval_minutes * 60,
            coalesce=True,
        )
        scheduler.add_job(
            jobs.run_daily_summary,
            trigger=CronTrigger(
                day_of_week="mon-fri", hour=sum_h, minute=sum_m, timezone=settings.market_tz
            ),
            id="daily_summary",
            name="End-of-day paper summary",
            misfire_grace_time=3600,
            coalesce=True,
        )

    logger.info(
        "Agent started — daily eval {:02d}:{:02d}, paper engine {} ({}). Ctrl-C to stop.",
        settings.eod_eval_hour,
        settings.eod_eval_minute,
        "ON" if settings.enable_paper_trading else "OFF",
        settings.market_tz,
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Agent stopped.")
