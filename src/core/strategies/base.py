"""Abstract strategy interface and the :class:`Signal` value object.

Every strategy takes a ticker's daily OHLCV frame and returns exactly one
:class:`Signal`. The orchestrator (Session 4) treats all strategies uniformly
through :meth:`Strategy.evaluate`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date as Date
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from src.core import patterns
from src.core.patterns import PatternHit

# Shared sentinel statuses used by every strategy.
NO_SIGNAL = "NO_SIGNAL"  # strategy is dormant/irrelevant for this ticker
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"  # not enough bars to classify


@dataclass(frozen=True)
class Signal:
    """A strategy's classification of one ticker on one date."""

    ticker: str
    strategy_name: str
    status: str
    details: dict[str, Any] = field(default_factory=dict)
    confidence: int = 0  # 0-3 stars
    patterns_detected: list[str] = field(default_factory=list)
    date: Date | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_actionable(self) -> bool:
        return self.status not in (NO_SIGNAL, INSUFFICIENT_DATA)


class Strategy(ABC):
    """Base class for all entry strategies."""

    #: stable identifier stored in the DB and shown in the dashboard
    name: str = "base"
    #: minimum bars required to attempt a classification
    min_bars: int = 2

    @abstractmethod
    def classify(self, df: pd.DataFrame) -> tuple[str, dict[str, Any]]:
        """Return ``(status, details)`` for the latest bar. Subclass implements this."""
        raise NotImplementedError

    def evaluate(self, ticker: str, df: pd.DataFrame) -> Signal:
        """Classify ``df``, attach bullish-pattern confidence, and build a Signal.

        Handles the shared concerns (empty/thin data, pattern detection, scoring)
        so subclasses only implement :meth:`classify`.
        """
        ticker = ticker.upper()
        if df is None or df.empty:
            return Signal(ticker, self.name, INSUFFICIENT_DATA, {"reason": "no data"})

        bar_date = pd.Timestamp(df.index[-1]).date()

        if len(df) < self.min_bars:
            return self._signal(ticker, INSUFFICIENT_DATA, {"n_bars": len(df)}, [], bar_date)

        status, details = self.classify(df)
        if status in (NO_SIGNAL, INSUFFICIENT_DATA):
            return self._signal(ticker, status, details, [], bar_date)

        hits: list[PatternHit] = patterns.detect_bullish_patterns(df)
        confidence = patterns.score_confidence(status, hits)
        return self._signal(ticker, status, details, hits, bar_date, confidence)

    def _signal(
        self,
        ticker: str,
        status: str,
        details: dict[str, Any],
        hits: list[PatternHit],
        bar_date: Date,
        confidence: int = 0,
    ) -> Signal:
        return Signal(
            ticker=ticker,
            strategy_name=self.name,
            status=status,
            details=details,
            confidence=confidence,
            patterns_detected=patterns.pattern_names(hits),
            date=bar_date,
        )
