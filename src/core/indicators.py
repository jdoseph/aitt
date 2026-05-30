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


def true_range(df: pd.DataFrame) -> pd.Series:
    """Wilder's True Range per bar: max(H-L, |H-prevC|, |L-prevC|)."""
    prev_close = df["close"].shift(1)
    ranges = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1, skipna=True)


def atr(df: pd.DataFrame, window: int | None = None) -> pd.Series:
    """Average True Range via Wilder's smoothing (EWM, alpha = 1/window)."""
    window = window or settings.atr_window
    tr = true_range(df)
    return tr.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()


def crowding_score(
    df: pd.DataFrame,
    ema_200: float | None,
    atr_val: float | None,
    lookback: int | None = None,
    atr_extended: float | None = None,
) -> float | None:
    """Volatility-normalized 0-100 crowding/extension score (higher = more extended).

    Blends how many ATRs the price sits above its 200 EMA with the recent run-up,
    both normalized by ATR so a calm name and a volatile name at the *same* percent
    distance score differently. ``None`` when the 200 EMA or ATR isn't available.
    """
    if ema_200 is None or atr_val is None or atr_val <= 0:
        return None
    lookback = lookback or settings.crowding_lookback
    atr_extended = atr_extended or settings.crowding_atr_extended
    close = float(df["close"].iloc[-1])
    ext_atrs = max(0.0, (close - ema_200) / atr_val)
    ext_norm = min(1.0, ext_atrs / atr_extended)
    if len(df) > lookback:
        past = float(df["close"].iloc[-1 - lookback])
        runup_atrs = max(0.0, (close - past) / atr_val)
        runup_norm = min(1.0, runup_atrs / atr_extended)
    else:
        runup_norm = 0.0
    return round(100.0 * (0.6 * ext_norm + 0.4 * runup_norm), 1)


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
    # Session 12: volatility-normalized extension. None when history is too thin.
    atr: float | None = None
    atr_pct: float | None = None
    crowding: float | None = None

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

    atr_series = atr(df)
    atr_last = atr_series.iloc[-1]
    atr_val = None if pd.isna(atr_last) else float(atr_last)
    atr_pct = (atr_val / close * 100.0) if (atr_val is not None and close) else None
    crowding = crowding_score(df, e200, atr_val)

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
        atr=atr_val,
        atr_pct=atr_pct,
        crowding=crowding,
    )
