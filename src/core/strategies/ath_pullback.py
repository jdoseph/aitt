"""Strategy 3 — Percentage Pullback from All-Time High.

For hot names trading at/near highs where EMAs are too far below to be useful:
buy meaningful dips in a confirmed uptrend.

Statuses (latest bar), by ``pullback_pct = (ATH - close) / ATH * 100``:
  AT_ATH         within ``ath_at_pct`` of the ATH
  MINOR_PULLBACK ath_at_pct .. ath_entry_low_pct below ATH
  ENTRY_ZONE     ath_entry_low_pct .. ath_entry_high_pct below ATH  -- primary alert
  DEEP_PULLBACK  ath_entry_high_pct .. ath_deep_pct below ATH       -- secondary alert
  CORRECTION     more than ath_deep_pct below ATH (no longer a dip buy)

Freshness: ``details["ath_fresh"]`` is True only if a new ATH was made within
``ath_freshness_days`` trading bars. Session 4 suppresses alerts on stale highs.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.core.config import settings
from src.core.indicators import compute_metrics
from src.core.strategies.base import Strategy

AT_ATH = "AT_ATH"
MINOR_PULLBACK = "MINOR_PULLBACK"
ENTRY_ZONE = "ENTRY_ZONE"
DEEP_PULLBACK = "DEEP_PULLBACK"
CORRECTION = "CORRECTION"


class ATHPullbackStrategy(Strategy):
    name = "ath_pullback"
    min_bars = 20  # enough history for a meaningful "high"

    def classify(self, df: pd.DataFrame) -> tuple[str, dict[str, Any]]:
        m = compute_metrics(df)
        pb = m.pullback_from_ath_pct

        if pb <= settings.ath_at_pct:
            status = AT_ATH
        elif pb <= settings.ath_entry_low_pct:
            status = MINOR_PULLBACK
        elif pb <= settings.ath_entry_high_pct:
            status = ENTRY_ZONE
        elif pb <= settings.ath_deep_pct:
            status = DEEP_PULLBACK
        else:
            status = CORRECTION

        ath_fresh = m.bars_since_ath <= settings.ath_freshness_days
        details: dict[str, Any] = {
            "close": round(m.close, 4),
            "ath": round(m.ath, 4),
            "pullback_pct": round(pb, 2),
            "bars_since_ath": m.bars_since_ath,
            "ath_fresh": ath_fresh,
            "vol_ratio": round(m.vol_ratio, 2),
        }
        return status, details
