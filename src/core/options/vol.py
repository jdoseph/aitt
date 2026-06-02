"""Realized-volatility proxy used as the IV fallback and the backtest IV source."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.core.config import settings


def realized_vol(
    df: pd.DataFrame,
    *,
    window: int | None = None,
    premium_mult: float | None = None,
    fallback: float = 0.40,
) -> float:
    """Annualized stdev of the last ``window`` daily log returns, x ``premium_mult``.

    Returns ``fallback`` when there isn't enough history (< window+1 closes).
    """
    window = window if window is not None else settings.realized_vol_window
    premium_mult = (
        premium_mult if premium_mult is not None else settings.option_iv_premium_mult
    )
    if df is None or df.empty or "close" not in df.columns or len(df) < window + 1:
        return fallback
    closes = df["close"].to_numpy(dtype=float)[-(window + 1):]
    log_returns = np.diff(np.log(closes))
    daily = float(np.std(log_returns, ddof=1))
    return daily * float(np.sqrt(252.0)) * premium_mult
