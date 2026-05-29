"""Strategy 2 — Breakout from Consolidation / Flag.

For extended names that have run up then gone sideways: the consolidation IS the
setup, and a close above the range on above-average volume is the entry.

Approach: walk backwards from the bar *before* the latest one, growing a base as
long as its (high-low)/low width stays within ``consolidation_range_pct``. That
yields the natural "N+ day" base length. The latest bar is then judged against
the base's high/low and a volume filter (vs the prior 20-day average volume).

Statuses (latest bar):
  CONSOLIDATING  a tight base of >= ``consolidation_min_days`` exists and the
                 latest close is still inside it (or poked out without volume)
  BREAKOUT       close above the base high on volume > mult x avg  -- alert
  BREAKDOWN      close below the base low on volume > mult x avg   -- warning
  NO_PATTERN     no tight base of sufficient length
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.core.config import settings
from src.core.strategies.base import INSUFFICIENT_DATA, Strategy

CONSOLIDATING = "CONSOLIDATING"
BREAKOUT = "BREAKOUT"
BREAKDOWN = "BREAKDOWN"
NO_PATTERN = "NO_PATTERN"


def _find_base(highs: list[float], lows: list[float], range_pct: float) -> tuple[float, float, int]:
    """Grow a base backwards from the newest bar while width stays <= range_pct.

    Returns (base_high, base_low, days_in_range).
    """
    rh, rl, count = highs[-1], lows[-1], 1
    for i in range(len(highs) - 2, -1, -1):
        new_rh, new_rl = max(rh, highs[i]), min(rl, lows[i])
        width = (new_rh - new_rl) / new_rl * 100 if new_rl else float("inf")
        if width > range_pct:
            break
        rh, rl, count = new_rh, new_rl, count + 1
    return rh, rl, count


class ConsolidationBreakoutStrategy(Strategy):
    name = "consolidation_breakout"

    @property
    def min_bars(self) -> int:  # type: ignore[override]
        return settings.consolidation_min_days + 1

    def classify(self, df: pd.DataFrame) -> tuple[str, dict[str, Any]]:
        if len(df) < settings.consolidation_min_days + 1:
            return INSUFFICIENT_DATA, {"n_bars": len(df)}

        base_df = df.iloc[:-1]  # everything before the latest bar
        base_high, base_low, days_in_range = _find_base(
            base_df["high"].tolist(), base_df["low"].tolist(), settings.consolidation_range_pct
        )
        range_width_pct = (base_high - base_low) / base_low * 100 if base_low else 0.0

        last = df.iloc[-1]
        close = float(last["close"])
        volume = float(last["volume"])
        # Prior N-day average volume (excludes the current bar).
        vol_avg = float(
            base_df["volume"].tail(settings.volume_avg_window).mean()
        )
        vol_ratio = (volume / vol_avg) if vol_avg else 0.0
        vol_confirm = vol_ratio >= settings.breakout_volume_mult

        details: dict[str, Any] = {
            "close": round(close, 4),
            "range_high": round(base_high, 4),
            "range_low": round(base_low, 4),
            "range_width_pct": round(range_width_pct, 2),
            "days_in_range": days_in_range,
            "vol_ratio": round(vol_ratio, 2),
            "vol_confirm": vol_confirm,
        }

        if days_in_range < settings.consolidation_min_days:
            return NO_PATTERN, details

        if close > base_high:
            status = BREAKOUT if vol_confirm else CONSOLIDATING
            details["unconfirmed_breakout"] = close > base_high and not vol_confirm
        elif close < base_low:
            status = BREAKDOWN if vol_confirm else CONSOLIDATING
            details["unconfirmed_breakdown"] = close < base_low and not vol_confirm
        else:
            status = CONSOLIDATING
        return status, details
