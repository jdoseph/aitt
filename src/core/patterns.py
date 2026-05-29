"""Bullish candlestick pattern detection + confidence scoring.

Patterns are a *confirmation layer*, not a standalone strategy: a strategy
classifies a ticker's status (e.g. ``AT_21_EMA``), then :func:`score_confidence`
turns the status' base score plus any bullish pattern in the last few candles
into a 1-3 star rating.

Detection uses TA-Lib (via the installed ``talib`` wheel). Each TA-Lib candle
function returns an int Series: +100 = bullish instance, -100 = bearish, 0 = none.
We keep only bullish (>0) hits, except the doji, which is non-directional and
only counts as confirmation when the signal sits at a support level.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

import pandas as pd
import talib

Strength = Literal["strong", "moderate", "weak"]

# pattern name -> (TA-Lib function, strength)
_PATTERN_FUNCS: Final[dict[str, tuple[object, Strength]]] = {
    "bullish_engulfing": (talib.CDLENGULFING, "strong"),
    "morning_star": (talib.CDLMORNINGSTAR, "strong"),
    "hammer": (talib.CDLHAMMER, "moderate"),
    "three_white_soldiers": (talib.CDL3WHITESOLDIERS, "moderate"),
    "piercing_line": (talib.CDLPIERCING, "moderate"),
    "doji": (talib.CDLDOJI, "weak"),
}

# Statuses where a doji is meaningful (indecision *at support* -> possible reversal).
SUPPORT_STATUSES: Final[frozenset[str]] = frozenset(
    {"AT_9_EMA", "AT_21_EMA", "ENTRY_ZONE", "MINOR_PULLBACK"}
)

# Base confidence score per actionable signal status (everything else = 0).
BASE_SCORES: Final[dict[str, int]] = {
    "AT_9_EMA": 1,
    "AT_21_EMA": 1,
    "ENTRY_ZONE": 1,
    "BREAKOUT": 2,
    "IPO_BREAKOUT": 2,
}

_STRONG: Final[frozenset[str]] = frozenset({"bullish_engulfing", "morning_star"})
_MODERATE: Final[frozenset[str]] = frozenset(
    {"hammer", "three_white_soldiers", "piercing_line"}
)


@dataclass(frozen=True)
class PatternHit:
    """A detected bullish pattern."""

    name: str
    strength: Strength
    bar_offset: int  # bars back from the latest candle (0 = latest)


def detect_bullish_patterns(df: pd.DataFrame, lookback: int = 3) -> list[PatternHit]:
    """Detect bullish candlestick patterns within the last ``lookback`` candles.

    Returns one :class:`PatternHit` per pattern type that fired (using the most
    recent occurrence within the window), ordered strong -> moderate -> weak.
    """
    if len(df) < 2:
        return []

    o = df["open"].to_numpy(dtype="float64")
    h = df["high"].to_numpy(dtype="float64")
    low = df["low"].to_numpy(dtype="float64")
    c = df["close"].to_numpy(dtype="float64")
    window = min(lookback, len(df))

    hits: list[PatternHit] = []
    for name, (func, strength) in _PATTERN_FUNCS.items():
        result = func(o, h, low, c)  # type: ignore[operator]
        tail = result[-window:]
        # doji is non-directional (TA-Lib returns +100); others must be bullish (>0).
        bullish_idx = [i for i, v in enumerate(tail) if (v != 0 if name == "doji" else v > 0)]
        if not bullish_idx:
            continue
        most_recent = bullish_idx[-1]
        bar_offset = (window - 1) - most_recent
        hits.append(PatternHit(name=name, strength=strength, bar_offset=bar_offset))

    order = {"strong": 0, "moderate": 1, "weak": 2}
    hits.sort(key=lambda hit: (order[hit.strength], hit.bar_offset))
    return hits


def score_confidence(status: str, patterns: list[PatternHit]) -> int:
    """Combine a status' base score with pattern confirmation into 1-3 stars.

    Returns 0 for non-actionable statuses with no base score (so the dashboard
    shows "no confidence" rather than a misleading star).
    """
    base = BASE_SCORES.get(status, 0)
    if base == 0:
        return 0

    names = {p.name for p in patterns}
    bonus = 0
    if names & _STRONG:
        bonus = 2
    elif names & _MODERATE:
        bonus = 1
    elif "doji" in names and status in SUPPORT_STATUSES:
        bonus = 1

    return min(3, base + bonus)


def pattern_names(patterns: list[PatternHit]) -> list[str]:
    """Convenience: just the pattern names (for storage / display)."""
    return [p.name for p in patterns]
