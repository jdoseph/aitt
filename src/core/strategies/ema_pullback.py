"""Strategy 1 — EMA Pullback.

For trending, non-parabolic names: watch for the price pulling back to its 9 or
21 EMA. Touch of the 21 EMA is the primary alert.

Statuses (latest bar):
  EXTENDED       price > ``ema_extended_pct`` above the 21 EMA (too far to act)
  APPROACHING_9  within ``ema_approaching_9_pct`` above the 9 EMA
  AT_9_EMA       bar touched/crossed the 9 EMA intrabar (still above 21)
  APPROACHING_21 within ``ema_approaching_21_pct`` above the 21 EMA (below the 9)
  AT_21_EMA      bar touched/crossed the 21 EMA intrabar  -- primary alert
  BELOW_21_EMA   whole bar below the 21 EMA (trend may be invalidated)
  NEUTRAL        in-trend but between the actionable bands (not in the spec's six;
                 an explicit "nothing to do" bucket so 3-8% above 21 isn't mislabeled)
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.core.config import settings
from src.core.indicators import compute_metrics
from src.core.strategies.base import INSUFFICIENT_DATA, Strategy

EXTENDED = "EXTENDED"
APPROACHING_9 = "APPROACHING_9"
AT_9_EMA = "AT_9_EMA"
APPROACHING_21 = "APPROACHING_21"
AT_21_EMA = "AT_21_EMA"
BELOW_21_EMA = "BELOW_21_EMA"
NEUTRAL = "NEUTRAL"


class EMAPullbackStrategy(Strategy):
    name = "ema_pullback"
    min_bars = 21  # need a meaningful 21 EMA

    def classify(self, df: pd.DataFrame) -> tuple[str, dict[str, Any]]:
        m = compute_metrics(df)
        if m.ema_9 is None or m.ema_21 is None:
            return INSUFFICIENT_DATA, {"n_bars": m.n_bars}

        e9, e21 = m.ema_9, m.ema_21
        high, low, close = m.high, m.low, m.close

        if high < e21:
            status = BELOW_21_EMA
        elif low <= e21 <= high:
            status = AT_21_EMA
        elif low <= e9 <= high:
            status = AT_9_EMA
        elif close < e9:
            # between the 9 and 21 EMAs, not touching either
            status = (
                APPROACHING_21
                if (m.dist_ema_21_pct or 0.0) <= settings.ema_approaching_21_pct
                else NEUTRAL
            )
        else:
            # entirely above the 9 EMA
            if (m.dist_ema_9_pct or 0.0) <= settings.ema_approaching_9_pct:
                status = APPROACHING_9
            elif (m.dist_ema_21_pct or 0.0) > settings.ema_extended_pct:
                status = EXTENDED
            else:
                status = NEUTRAL

        trend_ok = m.above_50_ema  # None if <50 bars
        details: dict[str, Any] = {
            "close": round(close, 4),
            "ema_9": round(e9, 4),
            "ema_21": round(e21, 4),
            "ema_50": None if m.ema_50 is None else round(m.ema_50, 4),
            "dist_ema_9_pct": None if m.dist_ema_9_pct is None else round(m.dist_ema_9_pct, 2),
            "dist_ema_21_pct": None if m.dist_ema_21_pct is None else round(m.dist_ema_21_pct, 2),
            "dist_ema_50_pct": None if m.dist_ema_50_pct is None else round(m.dist_ema_50_pct, 2),
            "vol_ratio": round(m.vol_ratio, 2),
            "trend_ok": trend_ok,
            "trend_filter_on": settings.use_trend_filter,
        }
        return status, details
