"""Technical indicators: EMAs, all-time-high, distances, average volume.

Pure functions over a date-indexed OHLCV frame (the shape
:func:`src.core.data.fetch_prices` returns). Strategies consume
:func:`compute_metrics`, which returns the latest-bar snapshot they classify on.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.core.config import settings


def ema(close: pd.Series, span: int) -> pd.Series:
    """Exponential moving average of ``close`` with the given span."""
    return close.ewm(span=span, adjust=False).mean()


def add_emas(df: pd.DataFrame, spans: tuple[int, ...] = (9, 21, 50)) -> pd.DataFrame:
    """Return a copy of ``df`` with ``ema_<span>`` columns added."""
    out = df.copy()
    for span in spans:
        out[f"ema_{span}"] = ema(out["close"], span)
    return out


def average_volume(df: pd.DataFrame, window: int | None = None) -> pd.Series:
    """Rolling simple average of volume over ``window`` bars."""
    window = window or settings.volume_avg_window
    return df["volume"].rolling(window=window, min_periods=1).mean()


def distance_pct(value: float, reference: float) -> float:
    """Percentage distance of ``value`` above/below ``reference`` (signed)."""
    if reference == 0:
        return 0.0
    return (value - reference) / reference * 100.0


def all_time_high(df: pd.DataFrame, lookback: int | None = None) -> tuple[float, int]:
    """Return (ATH, bars_since_ATH) using the intraday ``high`` series.

    ATH is the max high over the last ``lookback`` bars (or all rows if None).
    bars_since is counted from the most recent bar (0 = ATH is the latest bar).
    """
    highs = df["high"] if lookback is None else df["high"].tail(lookback)
    arr = highs.to_numpy()
    ath = float(arr.max())
    # Last occurrence of the max => most conservative "freshness" measure.
    last_pos = len(arr) - 1 - arr[::-1].argmax()
    bars_since = (len(arr) - 1) - last_pos
    return ath, int(bars_since)


@dataclass(frozen=True)
class Metrics:
    """Latest-bar indicator snapshot used by strategies."""

    n_bars: int
    close: float
    high: float
    low: float
    volume: float
    ema_9: float | None
    ema_21: float | None
    ema_50: float | None
    ema_200: float | None
    dist_ema_9_pct: float | None
    dist_ema_21_pct: float | None
    dist_ema_50_pct: float | None
    dist_ema_200_pct: float | None
    ath: float
    bars_since_ath: int
    pullback_from_ath_pct: float
    vol_avg: float
    vol_ratio: float

    @property
    def above_50_ema(self) -> bool | None:
        if self.ema_50 is None:
            return None
        return self.close > self.ema_50

    @property
    def above_200_ema(self) -> bool | None:
        if self.ema_200 is None:
            return None
        return self.close > self.ema_200


def compute_metrics(df: pd.DataFrame, ath_lookback: int | None = None) -> Metrics:
    """Compute the latest-bar :class:`Metrics` snapshot.

    EMA fields are ``None`` when there aren't enough bars for that span, so
    strategies can decide how to handle thin history rather than trusting a
    half-warmed EMA.
    """
    n = len(df)
    last = df.iloc[-1]
    close = float(last["close"])

    def ema_last(span: int) -> float | None:
        if n < span:
            return None
        return float(ema(df["close"], span).iloc[-1])

    e9, e21, e50, e200 = ema_last(9), ema_last(21), ema_last(50), ema_last(200)
    ath, bars_since = all_time_high(df, ath_lookback)
    vol_avg = float(average_volume(df).iloc[-1])
    volume = float(last["volume"])
    pullback_pct = ((ath - close) / ath * 100.0) if ath else 0.0

    return Metrics(
        n_bars=n,
        close=close,
        high=float(last["high"]),
        low=float(last["low"]),
        volume=volume,
        ema_9=e9,
        ema_21=e21,
        ema_50=e50,
        ema_200=e200,
        dist_ema_9_pct=None if e9 is None else distance_pct(close, e9),
        dist_ema_21_pct=None if e21 is None else distance_pct(close, e21),
        dist_ema_50_pct=None if e50 is None else distance_pct(close, e50),
        dist_ema_200_pct=None if e200 is None else distance_pct(close, e200),
        ath=ath,
        bars_since_ath=bars_since,
        pullback_from_ath_pct=pullback_pct,
        vol_avg=vol_avg,
        vol_ratio=(volume / vol_avg) if vol_avg else 0.0,
    )
