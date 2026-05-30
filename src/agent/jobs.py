"""Agent jobs: refresh prices, evaluate signals, fire alerts, and the full cycle.

These are plain functions so they can be called from the scheduler, the CLI
(``--once``), or tests. Each is defensive: a single failing ticker is logged and
skipped, never aborting the cycle.
"""

from __future__ import annotations

import pandas as pd
from loguru import logger

from src.agent import notify
from src.core import backtest, benchmarks, earnings, news
from src.core.config import settings
from src.core.data import fetch_many
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
    )
    return engine.run_cycle(price_map)


def fire_alerts(result: CycleResult) -> int:
    """Dispatch the cycle's alerts to all enabled notification channels."""
    return notify.dispatch(result.alerts)


def run_once(store: Storage | None = None, *, fetch: bool = True) -> CycleResult:
    """One full evaluation cycle: (optionally fetch) -> evaluate -> alert -> summarize."""
    store = store or Storage()
    if fetch:
        frames = refresh_prices(store)
        result = evaluate_signals(store, frames)
    else:
        result = evaluate_signals(store)

    fire_alerts(result)
    logger.info(
        "cycle done: {} tickers, {} signals, {} alerts (date={}) | statuses={}",
        result.n_tickers,
        result.n_signals,
        len(result.alerts),
        result.bar_date,
        result.status_counts,
    )
    return result
