"""CLI entry point.

    python -m src.agent          # run the daily-close scheduler (blocking)
    python -m src.agent --once   # run a single evaluation cycle now, then exit
    python -m src.agent --once --no-fetch   # evaluate using prices already in the DB
    python -m src.agent --validate          # check the watchlist loads + every ticker fetches
"""

from __future__ import annotations

import argparse
import sys

from loguru import logger

from src.agent import jobs, scheduler
from src.core.config import settings


def _configure_logging() -> None:
    # Windows consoles default to cp1252 and choke on the star/emoji glyphs we
    # emit. Force UTF-8 on the std streams where supported (no-op if redirected).
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
    logger.remove()
    logger.add(sys.stderr, level=settings.log_level)
    # Persistent rotating file sink for unattended (overnight/daily) runs.
    if settings.file_logging_enabled:
        settings.log_file.parent.mkdir(parents=True, exist_ok=True)
        logger.add(
            settings.log_file,
            level=settings.log_level,
            rotation=settings.log_rotation,
            retention=settings.log_retention,
            encoding="utf-8",
            enqueue=True,  # safe across the scheduler thread
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.agent", description="AI infra tracker agent")
    parser.add_argument("--once", action="store_true", help="run a single cycle and exit")
    parser.add_argument(
        "--no-fetch",
        action="store_true",
        help="with --once, skip fetching and use prices already stored in the DB",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="check the watchlist loads and every ticker is fetchable, then exit",
    )
    args = parser.parse_args(argv)

    _configure_logging()
    settings.ensure_dirs()

    if args.validate:
        report = jobs.validate_watchlist()
        (logger.info if report.all_ok else logger.warning)(report.summary())
        return 0 if report.all_ok else 1

    if args.once:
        result = jobs.run_once(fetch=not args.no_fetch)
        # Surface the top alerts on stdout for quick eyeballing.
        for alert in result.alerts[:10]:
            print(f"  {'⭐' * alert.confidence or '•':<3} {alert.message}")
        return 0

    scheduler.run_scheduled()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
