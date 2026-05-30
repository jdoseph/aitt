"""Relative strength vs market benchmarks (SPY / QQQ / SMH).

`fetch_benchmarks` pulls the benchmark frames once per cycle (through the same
`data.fetch_prices` seam); `relative_strength` compares a ticker's trailing
return to a benchmark's. The scorecard's rel-strength check (Session 7) reduces
these to pass/warn/fail.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd
from loguru import logger

from src.core.config import settings


def return_pct(df: pd.DataFrame, lookback: int) -> float | None:
    """Percent change of close over the last ``lookback`` bars (None if too short)."""
    if df is None or len(df) < lookback + 1:
        return None
    closes = df["close"]
    past, now = float(closes.iloc[-1 - lookback]), float(closes.iloc[-1])
    if past == 0:
        return None
    return (now - past) / past * 100.0


@dataclass(frozen=True)
class RelStrength:
    benchmark: str
    ticker_return: float
    bench_return: float
    delta: float  # ticker - benchmark (positive = outperforming)

    @property
    def outperform(self) -> bool:
        return self.delta > 0


def relative_strength(
    ticker_df: pd.DataFrame, bench_df: pd.DataFrame, benchmark: str, lookback: int | None = None
) -> RelStrength | None:
    """Trailing-return comparison of a ticker vs one benchmark over ``lookback`` bars."""
    lookback = lookback or settings.rs_lookback
    tr = return_pct(ticker_df, lookback)
    br = return_pct(bench_df, lookback)
    if tr is None or br is None:
        return None
    return RelStrength(benchmark=benchmark, ticker_return=tr, bench_return=br, delta=tr - br)


def relative_strength_all(
    ticker_df: pd.DataFrame, benchmarks: dict[str, pd.DataFrame], lookback: int | None = None
) -> list[RelStrength]:
    """One :class:`RelStrength` per available benchmark (skips ones with no data)."""
    out: list[RelStrength] = []
    for name, bdf in benchmarks.items():
        rs = relative_strength(ticker_df, bdf, name, lookback)
        if rs is not None:
            out.append(rs)
    return out


_cache: dict[tuple[str, ...], tuple[date, dict[str, pd.DataFrame]]] = {}


def fetch_benchmarks(symbols: list[str] | None = None) -> dict[str, pd.DataFrame]:
    """Fetch benchmark price frames once per day (in-process cache), best-effort."""
    from src.core.data import DataFetchError, fetch_prices  # local import avoids cycle

    symbols = symbols or settings.rs_benchmarks
    key = tuple(symbols)
    today = date.today()
    cached = _cache.get(key)
    if cached and cached[0] == today:
        return cached[1]

    frames: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        try:
            frames[sym] = fetch_prices(sym)
        except DataFetchError as exc:
            logger.warning("benchmark {} unavailable: {}", sym, exc)
    _cache[key] = (today, frames)
    return frames
