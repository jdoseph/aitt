"""Agent jobs: refresh prices, evaluate signals, fire alerts, and the full cycle.

These are plain functions so they can be called from the scheduler, the CLI
(``--once``), or tests. Each is defensive: a single failing ticker is logged and
skipped, never aborting the cycle.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import pandas as pd
from loguru import logger

from src.agent import notify
from src.core import backtest, benchmarks, earnings, news
from src.core.config import settings
from src.core.data import DataFetchError, fetch_many, fetch_prices
from src.core.signals import CycleResult, SignalEngine
from src.core.storage import Storage
from src.core.watchlist import load_watchlist


def refresh_prices(store: Storage, tickers: list[str] | None = None) -> dict[str, pd.DataFrame]:
    """Batch-fetch all watchlist tickers and upsert them into storage."""
    tickers = tickers or load_watchlist().tickers
    frames = fetch_many(tickers)
    for ticker, df in frames.items():
        store.upsert_prices(ticker, df)
    return frames


def evaluate_signals(
    store: Storage, price_map: dict[str, pd.DataFrame] | None = None
) -> CycleResult:
    """Run the orchestrator. If ``price_map`` is None, read the latest prices from the DB."""
    if price_map is None:
        price_map = {t: store.get_prices(t) for t in load_watchlist().tickers}
        price_map = {t: df for t, df in price_map.items() if not df.empty}
    # Wire in the real (network) scorecard + evidence providers. The engine fetches
    # benchmarks once and earnings/news per gradeable ticker; the historical backtest
    # is cached in the DB and refreshed weekly.
    fetcher = backtest.make_fetcher()
    engine = SignalEngine(
        store,
        benchmark_provider=benchmarks.fetch_benchmarks,
        earnings_provider=earnings.days_to_earnings,
        historical_provider=(
            (lambda t, s, st: backtest.compute_stats(t, s, st, store=store, fetcher=fetcher))
            if settings.enable_backtest
            else None
        ),
        earnings_beat_provider=news.earnings_beat,
        news_provider=news.recent_headlines,
        benchmark_price_provider=_latest_benchmark_close,
    )
    return engine.run_cycle(price_map)


def _latest_benchmark_close() -> float | None:
    """Latest close of the portfolio benchmark (VOO) for the NAV overlay."""
    from src.core.data import DataFetchError, fetch_prices

    try:
        df = fetch_prices(settings.portfolio_benchmark, bars=5)
    except DataFetchError:
        return None
    return None if df.empty else float(df["close"].iloc[-1])


def fire_alerts(result: CycleResult) -> int:
    """Dispatch the cycle's alerts to all enabled notification channels."""
    return notify.dispatch(result.alerts)


@dataclass
class ValidationReport:
    """Result of a startup watchlist/config check (see :func:`validate_watchlist`)."""

    ok: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)  # ticker -> reason

    @property
    def all_ok(self) -> bool:
        return not self.failed

    def summary(self) -> str:
        n = len(self.ok) + len(self.failed)
        line = f"watchlist: {len(self.ok)}/{n} tickers fetchable"
        if self.failed:
            detail = ", ".join(f"{t} ({why})" for t, why in self.failed.items())
            return f"{line} — UNFETCHABLE: {detail}"
        return line + " — all OK"


def validate_watchlist(
    fetcher: Callable[[str, int], pd.DataFrame] | None = None,
) -> ValidationReport:
    """Load the watchlist (validating its schema) and check every ticker fetches.

    Loading raises on a malformed YAML/schema; reachability problems are collected
    per ticker rather than raised, so one bad symbol doesn't mask the rest.
    A small bar count keeps the check fast — we only need to confirm data exists.
    """
    fetch = fetcher or (lambda t, bars: fetch_prices(t, bars))
    report = ValidationReport()
    for ticker in load_watchlist().tickers:
        try:
            df = fetch(ticker, 5)
            if df.empty:
                report.failed[ticker] = "no data"
            else:
                report.ok.append(ticker)
        except DataFetchError as exc:
            report.failed[ticker] = str(exc)
        except Exception as exc:  # noqa: BLE001 - report, don't abort, on any provider error
            report.failed[ticker] = f"{type(exc).__name__}: {exc}"
    return report


def run_once(store: Storage | None = None, *, fetch: bool = True) -> CycleResult:
    """One full evaluation cycle: (optionally fetch) -> evaluate -> alert -> summarize."""
    store = store or Storage()
    if fetch:
        frames = refresh_prices(store)
        result = evaluate_signals(store, frames)
    else:
        result = evaluate_signals(store)

    fire_alerts(result)
    notify.log_portfolio_summary(result)
    logger.info(
        "cycle done: {} tickers, {} signals, {} alerts ({} suppressed) "
        "(date={}, regime={}, exposure={:.0%}) | statuses={}",
        result.n_tickers,
        result.n_signals,
        len(result.alerts),
        result.n_suppressed,
        result.bar_date,
        result.regime_label,
        result.exposure,
        result.status_counts,
    )
    return result
