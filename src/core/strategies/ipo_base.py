"""Strategy 4 — IPO Base.

Dormant for seasoned names; activates only for tickers with < ``ipo_max_history_days``
of trading history (e.g. Anthropic/OpenAI once they list and are added to the
watchlist). New issues typically spike, base for weeks below the initial high,
then break out — that breakout on volume is the entry.

Statuses:
  NO_SIGNAL     not an IPO (>= ipo_max_history_days of history)
  IPO_FRESH     < ipo_fresh_days of trading, too early to judge
  IPO_BASING    consolidating below the initial high, wait
  IPO_BREAKOUT  close above the initial high on volume > mult x avg  -- alert
  IPO_FAILED    dropped >= ipo_failed_drawdown_pct from the initial high, avoid
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.core.config import settings
from src.core.strategies.base import NO_SIGNAL, Strategy

IPO_FRESH = "IPO_FRESH"
IPO_BASING = "IPO_BASING"
IPO_BREAKOUT = "IPO_BREAKOUT"
IPO_FAILED = "IPO_FAILED"


class IPOBaseStrategy(Strategy):
    name = "ipo_base"
    min_bars = 1

    def classify(self, df: pd.DataFrame) -> tuple[str, dict[str, Any]]:
        n = len(df)
        if n >= settings.ipo_max_history_days:
            return NO_SIGNAL, {"n_bars": n, "reason": "not an IPO"}
        if n < settings.ipo_fresh_days:
            return IPO_FRESH, {"n_bars": n}

        initial = df.iloc[: settings.ipo_initial_high_days]
        ipo_high = float(initial["high"].max())

        last = df.iloc[-1]
        close = float(last["close"])
        volume = float(last["volume"])
        drawdown_pct = (ipo_high - close) / ipo_high * 100 if ipo_high else 0.0

        # Prior average volume (exclude current bar); fall back to all prior bars.
        prior = df["volume"].iloc[:-1].tail(settings.volume_avg_window)
        vol_avg = float(prior.mean()) if len(prior) else volume
        vol_ratio = (volume / vol_avg) if vol_avg else 0.0
        vol_confirm = vol_ratio >= settings.breakout_volume_mult

        details: dict[str, Any] = {
            "n_bars": n,
            "ipo_high": round(ipo_high, 4),
            "close": round(close, 4),
            "drawdown_from_high_pct": round(drawdown_pct, 2),
            "vol_ratio": round(vol_ratio, 2),
            "vol_confirm": vol_confirm,
        }

        if close > ipo_high and vol_confirm:
            status = IPO_BREAKOUT
        elif drawdown_pct >= settings.ipo_failed_drawdown_pct:
            status = IPO_FAILED
        else:
            status = IPO_BASING
        return status, details
