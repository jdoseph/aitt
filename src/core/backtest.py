"""Historical signal replay → forward win-rate (Session 8).

For a (ticker, strategy, status), replay the strategy's classifier bar-by-bar
over multi-year history, find every *transition into* that status, and measure
forward 5/10/20-day close-to-close returns. "Win" = positive forward return.

Results are cached in the ``backtest_stats`` table and refreshed weekly — the
replay is O(bars^2) per setup, so it must not run every cycle.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd
from loguru import logger

from src.core.config import settings
from src.core.storage import BacktestStat, Storage
from src.core.strategies.ath_pullback import ATHPullbackStrategy
from src.core.strategies.base import Strategy
from src.core.strategies.consolidation_breakout import ConsolidationBreakoutStrategy
from src.core.strategies.ema_pullback import EMAPullbackStrategy
from src.core.strategies.ipo_base import IPOBaseStrategy

STRATEGY_BY_NAME: dict[str, type[Strategy]] = {
    cls().name: cls
    for cls in (
        EMAPullbackStrategy,
        ATHPullbackStrategy,
        ConsolidationBreakoutStrategy,
        IPOBaseStrategy,
    )
}


@dataclass(frozen=True)
class HorizonStat:
    horizon: int
    n: int
    wins: int
    win_rate: float  # percent
    avg_return: float  # percent


@dataclass(frozen=True)
class HistoricalStat:
    ticker: str
    strategy: str
    status: str
    by_horizon: dict[int, HorizonStat]

    def primary(self, horizon: int | None = None) -> HorizonStat | None:
        return self.by_horizon.get(horizon or settings.backtest_primary_horizon)


def replay(
    df: pd.DataFrame,
    strategy: Strategy,
    target_status: str,
    horizons: Sequence[int],
) -> dict[int, HorizonStat]:
    """Replay ``strategy`` over ``df``, returning forward-return stats per horizon."""
    closes = df["close"].to_numpy(dtype="float64")
    n = len(df)
    start = max(1, getattr(strategy, "min_bars", 2) - 1)

    occurrences: list[int] = []
    prev_status: str | None = None
    for i in range(start, n):
        status, _ = strategy.classify(df.iloc[: i + 1])
        if status == target_status and prev_status != target_status:
            occurrences.append(i)
        prev_status = status

    out: dict[int, HorizonStat] = {}
    for h in horizons:
        rets = [closes[i + h] / closes[i] - 1.0 for i in occurrences if i + h < n]
        if rets:
            wins = sum(1 for r in rets if r > 0)
            out[h] = HorizonStat(h, len(rets), wins, wins / len(rets) * 100, sum(rets) / len(rets) * 100)
        else:
            out[h] = HorizonStat(h, 0, 0, 0.0, 0.0)
    return out


def _records_to_stat(
    ticker: str, strategy: str, status: str, records: Sequence[BacktestStat]
) -> HistoricalStat:
    by_h = {
        r.horizon: HorizonStat(r.horizon, r.n, r.wins, r.win_rate, r.avg_return) for r in records
    }
    return HistoricalStat(ticker.upper(), strategy, status, by_h)


def _is_fresh(records: Sequence[BacktestStat]) -> bool:
    if not records:
        return False
    newest = max(r.computed_at for r in records)
    if newest.tzinfo is None:
        newest = newest.replace(tzinfo=timezone.utc)
    age_days = (datetime.now(timezone.utc) - newest).days
    return age_days < settings.backtest_refresh_days


def compute_stats(
    ticker: str,
    strategy_name: str,
    status: str,
    *,
    store: Storage,
    fetcher: Callable[[str], pd.DataFrame],
    horizons: Sequence[int] | None = None,
) -> HistoricalStat | None:
    """Return cached or freshly-computed historical stats for a setup (None on failure)."""
    horizons = horizons or settings.backtest_horizons
    ticker = ticker.upper()

    cached = store.get_backtest_stats(ticker, strategy_name, status)
    if cached and _is_fresh(cached):
        return _records_to_stat(ticker, strategy_name, status, cached)

    cls = STRATEGY_BY_NAME.get(strategy_name)
    if cls is None:
        return None

    try:
        df = fetcher(ticker)
    except Exception as exc:  # noqa: BLE001 - extended fetch is best-effort
        logger.warning("backtest fetch failed for {}: {}", ticker, exc)
        return _records_to_stat(ticker, strategy_name, status, cached) if cached else None

    if df is None or df.empty:
        return None

    stats = replay(df, cls(), status, horizons)
    now = datetime.now(timezone.utc)
    records = [
        BacktestStat(
            ticker=ticker,
            strategy=strategy_name,
            status=status,
            horizon=h,
            n=s.n,
            wins=s.wins,
            win_rate=s.win_rate,
            avg_return=s.avg_return,
            computed_at=now,
        )
        for h, s in stats.items()
    ]
    store.upsert_backtest_stats(records)
    return HistoricalStat(ticker, strategy_name, status, stats)


def make_fetcher() -> Callable[[str], pd.DataFrame]:
    """Default extended-history fetcher (~3y) used by the agent."""
    from src.core.data import fetch_prices

    return lambda t: fetch_prices(t, bars=settings.backtest_history_bars)
