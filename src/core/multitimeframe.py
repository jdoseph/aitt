"""Weekly trend alignment (Session 12).

Resamples the daily frame to weekly bars and reads the higher-timeframe trend off
the 30-week moving average and its slope. A daily pullback inside a weekly uptrend
is a stronger setup than the same pullback inside a weekly downtrend — the
:func:`alignment` flag captures that.

Pure functions over a date-indexed daily OHLCV frame.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from src.core import market
from src.core.config import settings
from src.core.strategies.base import Signal

UPTREND, DOWNTREND, NEUTRAL = "uptrend", "downtrend", "neutral"
ALIGNED, COUNTER, NEUTRAL_ALIGN = "aligned", "counter", "neutral"

_AGG = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}


def to_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """Resample daily OHLCV to weekly bars (week ending Friday)."""
    weekly = df.resample("W-FRI").agg(_AGG)
    return weekly.dropna(subset=["close"])


@dataclass(frozen=True)
class WeeklyTrend:
    trend: str  # uptrend | downtrend | neutral
    above_ma: bool | None
    slope_pct: float | None  # % change of the 30-week MA over the slope window
    ma: float | None
    n_weeks: int

    def to_summary(self) -> dict[str, Any]:
        return {
            "trend": self.trend,
            "above_ma": self.above_ma,
            "slope_pct": None if self.slope_pct is None else round(self.slope_pct, 2),
            "ma": None if self.ma is None else round(self.ma, 2),
            "n_weeks": self.n_weeks,
        }


def weekly_trend(df: pd.DataFrame, weeks: int | None = None) -> WeeklyTrend:
    """Classify the weekly trend from price vs the 30-week MA and the MA's slope."""
    weeks = weeks or settings.weekly_ma_weeks
    weekly = to_weekly(df)
    n = len(weekly)
    if n < weeks:
        return WeeklyTrend(NEUTRAL, None, None, None, n)

    ma = weekly["close"].rolling(window=weeks, min_periods=weeks).mean()
    ma_now = float(ma.iloc[-1])
    close_now = float(weekly["close"].iloc[-1])
    above = close_now > ma_now

    lb = settings.weekly_slope_lookback
    if len(ma.dropna()) > lb:
        ma_past = float(ma.iloc[-1 - lb])
        slope_pct = (ma_now - ma_past) / ma_past * 100.0 if ma_past else 0.0
    else:
        slope_pct = 0.0

    flat = settings.weekly_slope_flat_pct
    if above and slope_pct > flat:
        trend = UPTREND
    elif (not above) and slope_pct < -flat:
        trend = DOWNTREND
    else:
        trend = NEUTRAL
    return WeeklyTrend(trend, above, slope_pct, ma_now, n)


def alignment(wt: WeeklyTrend, signal: Signal | None) -> str:
    """How the weekly trend lines up with a (typically bullish/pullback) daily setup.

    ``aligned``  — weekly uptrend supports the daily long setup (stronger).
    ``counter``  — weekly downtrend fights it (weaker).
    ``neutral``  — weekly trend is sideways / unknown.
    """
    if wt.trend == UPTREND:
        return ALIGNED
    if wt.trend == DOWNTREND:
        return COUNTER
    # Non-bullish daily statuses (e.g. a breakdown) don't earn an alignment read.
    if signal is not None and signal.status not in market.BULLISH_STATUSES:
        return NEUTRAL_ALIGN
    return NEUTRAL_ALIGN
