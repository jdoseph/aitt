"""Institutional accumulation/distribution signals (Session 12).

Volume-based reads on whether big money is *behind* a move: On-Balance Volume,
the Accumulation/Distribution line, the up-vs-down volume ratio, and where price
closes within its range. These roll into a 0-100 ``accumulation_score`` that feeds
the composite score's Volume-Accumulation category (Session 11) and the dossier.

Pure functions over a date-indexed OHLCV frame.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from src.core.config import settings

ACCUMULATION, NEUTRAL, DISTRIBUTION = "accumulation", "neutral", "distribution"


def obv(df: pd.DataFrame) -> pd.Series:
    """On-Balance Volume: running sum of signed volume by close direction."""
    direction = df["close"].diff().fillna(0.0)
    signed = df["volume"].where(direction > 0, -df["volume"]).where(direction != 0, 0.0)
    return signed.cumsum()


def ad_line(df: pd.DataFrame) -> pd.Series:
    """Accumulation/Distribution line (Chaikin): cumulative money-flow volume."""
    high, low, close = df["high"], df["low"], df["close"]
    span = (high - low).replace(0.0, pd.NA)
    mfm = ((close - low) - (high - close)) / span  # close-location value, [-1, 1]
    mfv = mfm.fillna(0.0) * df["volume"]
    return mfv.cumsum()


def up_down_volume_ratio(df: pd.DataFrame, lookback: int | None = None) -> float:
    """Sum of volume on up-closes / sum on down-closes over ``lookback`` bars.

    >1 means up-days carried more volume (demand). Returns a large finite number
    when there is no down-volume, and 1.0 when there's nothing to compare.
    """
    lookback = lookback or settings.accumulation_lookback
    tail = df.tail(lookback)
    direction = tail["close"].diff()
    up = float(tail["volume"][direction > 0].sum())
    down = float(tail["volume"][direction < 0].sum())
    if down == 0:
        return 999.0 if up > 0 else 1.0
    return up / down


def close_position_in_range(df: pd.DataFrame, lookback: int | None = None) -> float:
    """Average close-location value over ``lookback`` bars, in [0, 1].

    1.0 = closing at the high (buyers in control); 0.0 = closing at the low.
    """
    lookback = lookback or settings.accumulation_lookback
    tail = df.tail(lookback)
    span = (tail["high"] - tail["low"]).replace(0.0, pd.NA)
    pos = (tail["close"] - tail["low"]) / span
    return float(pos.fillna(0.5).mean())


@dataclass(frozen=True)
class AccumulationResult:
    score: float  # 0-100, higher = accumulation
    label: str  # accumulation | neutral | distribution
    obv_rising: bool
    ad_rising: bool
    ud_ratio: float
    close_pos: float

    def to_summary(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 1),
            "label": self.label,
            "obv_rising": self.obv_rising,
            "ad_rising": self.ad_rising,
            "ud_ratio": round(self.ud_ratio, 2),
            "close_pos": round(self.close_pos, 2),
        }


def _rising(series: pd.Series, lookback: int) -> bool:
    """True if the series ends higher than it was ``lookback`` bars ago."""
    if len(series) <= lookback:
        return bool(series.iloc[-1] > series.iloc[0])
    return bool(series.iloc[-1] > series.iloc[-1 - lookback])


def accumulation_score(df: pd.DataFrame, lookback: int | None = None) -> AccumulationResult:
    """Blend OBV trend, A/D trend, up/down volume, and close-in-range into 0-100.

    OBV rising + A/D rising + up-volume dominance + closes near the highs =
    institutions accumulating.
    """
    lookback = lookback or settings.accumulation_lookback
    obv_rising = _rising(obv(df), lookback)
    ad_rising = _rising(ad_line(df), lookback)
    ud_ratio = up_down_volume_ratio(df, lookback)
    close_pos = close_position_in_range(df, lookback)

    obv_norm = 1.0 if obv_rising else 0.0
    ad_norm = 1.0 if ad_rising else 0.0
    ud_norm = max(0.0, min(1.0, ud_ratio / 2.0))  # ratio 2.0 -> 1.0, 1.0 -> 0.5
    score = 100.0 * (obv_norm + ad_norm + ud_norm + close_pos) / 4.0

    if score >= settings.accumulation_acc_score:
        label = ACCUMULATION
    elif score <= settings.accumulation_dist_score:
        label = DISTRIBUTION
    else:
        label = NEUTRAL
    return AccumulationResult(
        score=score,
        label=label,
        obv_rising=obv_rising,
        ad_rising=ad_rising,
        ud_ratio=ud_ratio,
        close_pos=close_pos,
    )
