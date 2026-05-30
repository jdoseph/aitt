"""Price levels: swing-pivot resistance/support, suggested stop, risk/reward.

Pure functions over a date-indexed OHLCV frame. Used by the scorecard's
resistance/headroom and risk/reward checks (Session 7).
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.core.config import settings
from src.core.indicators import Metrics


def swing_highs(df: pd.DataFrame, k: int | None = None) -> list[float]:
    """Confirmed swing-high pivots: a bar whose high is the strict max of the
    ``2k+1`` window centered on it."""
    k = k or settings.swing_pivot_k
    h = df["high"].to_numpy(dtype="float64")
    n = len(h)
    out: list[float] = []
    for i in range(k, n - k):
        window = h[i - k : i + k + 1]
        if window.argmax() == k:  # center is the (first) max => a peak
            out.append(float(h[i]))
    return out


def swing_lows(df: pd.DataFrame, k: int | None = None) -> list[float]:
    """Confirmed swing-low pivots (mirror of :func:`swing_highs`)."""
    k = k or settings.swing_pivot_k
    low = df["low"].to_numpy(dtype="float64")
    n = len(low)
    out: list[float] = []
    for i in range(k, n - k):
        window = low[i - k : i + k + 1]
        if window.argmin() == k:
            out.append(float(low[i]))
    return out


def nearest_resistance(
    df: pd.DataFrame, price: float, lookback: int | None = None, k: int | None = None
) -> float | None:
    """Nearest swing-high strictly above ``price`` within ``lookback`` bars.

    Returns None when there is no overhead pivot (blue-sky / at highs).
    """
    lookback = lookback or settings.resistance_lookback
    highs = swing_highs(df.tail(lookback), k)
    above = [h for h in highs if h > price]
    return min(above) if above else None


def nearest_support(
    df: pd.DataFrame, price: float, lookback: int | None = None, k: int | None = None
) -> float | None:
    """Nearest swing-low strictly below ``price`` within ``lookback`` bars."""
    lookback = lookback or settings.resistance_lookback
    lows = swing_lows(df.tail(lookback), k)
    below = [low for low in lows if low < price]
    return max(below) if below else None


def suggested_stop(
    df: pd.DataFrame,
    price: float,
    lookback: int | None = None,
    k: int | None = None,
    fallback_pct: float | None = None,
) -> float:
    """A stop just under the nearest support; falls back to a fixed % below price."""
    fallback_pct = settings.fallback_stop_pct if fallback_pct is None else fallback_pct
    support = nearest_support(df, price, lookback, k)
    if support is not None and support < price:
        return round(support * 0.99, 4)
    return round(price * (1 - fallback_pct / 100), 4)


def risk_reward(entry: float, stop: float, target: float | None) -> float | None:
    """Reward-to-risk ratio. None if the geometry is invalid (no upside/downside)."""
    if target is None:
        return None
    risk = entry - stop
    reward = target - entry
    if risk <= 0 or reward <= 0:
        return None
    return reward / risk


# Plain-text invalidation per setup type (Session 9 dossier).
_INVALIDATION_TEXT = {
    "ema_pullback": "close below the 21 EMA",
    "consolidation_breakout": "breakdown back into the base (below the range low)",
    "ath_pullback": "loss of the recent swing low",
    "ipo_base": "drop back below the IPO base",
}


def strategy_stop(df: pd.DataFrame, signal: Any, metrics: Metrics) -> float:
    """A stop placed by setup type, not one-size-fits-all (Session 9 dossier).

    EMA pullback → just below the 21 EMA; consolidation → below the range low;
    IPO base → below the IPO high (the broken-out level); everything else (ATH
    dip) → the generic swing-low :func:`suggested_stop`.
    """
    strat = getattr(signal, "strategy_name", "")
    details = getattr(signal, "details", {}) or {}
    price = metrics.close

    if strat == "ema_pullback" and metrics.ema_21 is not None:
        return round(min(metrics.ema_21, price) * 0.99, 4)
    if strat == "consolidation_breakout":
        low = details.get("range_low")
        if low:
            return round(float(low) * 0.99, 4)
    if strat == "ipo_base":
        ipo_high = details.get("ipo_high")
        if ipo_high:
            return round(float(ipo_high) * 0.99, 4)
    return suggested_stop(df, price)


def invalidation_text(signal: Any) -> str:
    """Plain-language condition that would invalidate the setup."""
    return _INVALIDATION_TEXT.get(getattr(signal, "strategy_name", ""), "loss of the 50 EMA")
