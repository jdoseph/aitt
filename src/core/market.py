"""Portfolio-level context: AI-basket breadth and value-chain layer leadership.

Computed once per cycle from the full set of latest signals; feeds the
scorecard's "leading layer" and "breadth" checks (Session 7).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from src.core.config import settings
from src.core.watchlist import Watchlist

# Per-status sentiment. Anything not listed is treated as neutral.
BULLISH_STATUSES: frozenset[str] = frozenset(
    {
        "AT_21_EMA", "AT_9_EMA", "APPROACHING_9", "APPROACHING_21",
        "ENTRY_ZONE", "MINOR_PULLBACK", "AT_ATH",
        "BREAKOUT", "CONSOLIDATING",
        "IPO_BREAKOUT", "IPO_BASING", "IPO_FRESH",
    }
)
BEARISH_STATUSES: frozenset[str] = frozenset(
    {"BELOW_21_EMA", "CORRECTION", "BREAKDOWN", "IPO_FAILED"}
)
ENTRY_STATUSES: frozenset[str] = frozenset(
    {"AT_21_EMA", "AT_9_EMA", "ENTRY_ZONE", "BREAKOUT", "IPO_BREAKOUT"}
)


class SignalLike(Protocol):
    # Read-only members so frozen dataclasses (Signal) also satisfy the protocol.
    @property
    def ticker(self) -> str: ...
    @property
    def status(self) -> str: ...
    @property
    def confidence(self) -> int: ...


def ticker_sentiment(statuses: list[str]) -> str:
    """A ticker is bullish if any of its strategy statuses is bullish, else bearish
    if any is bearish, else neutral."""
    if any(s in BULLISH_STATUSES for s in statuses):
        return "bullish"
    if any(s in BEARISH_STATUSES for s in statuses):
        return "bearish"
    return "neutral"


@dataclass(frozen=True)
class Breadth:
    bullish: int
    neutral: int
    bearish: int
    total: int

    @property
    def healthy(self) -> bool:
        return self.total > 0 and (self.bullish / self.total) >= settings.breadth_healthy_pct

    def summary(self) -> str:
        return f"{self.bullish}/{self.total} bullish"


@dataclass(frozen=True)
class MarketContext:
    breadth: Breadth
    leadership: list[tuple[str, float]] = field(default_factory=list)  # (layer_key, score) desc
    leading_layers: frozenset[str] = frozenset()


def breadth(signals: Sequence[SignalLike]) -> Breadth:
    by_ticker: dict[str, list[str]] = defaultdict(list)
    for s in signals:
        by_ticker[s.ticker].append(s.status)
    counts = {"bullish": 0, "neutral": 0, "bearish": 0}
    for statuses in by_ticker.values():
        counts[ticker_sentiment(statuses)] += 1
    return Breadth(counts["bullish"], counts["neutral"], counts["bearish"], len(by_ticker))


def layer_leadership(
    signals: Sequence[SignalLike], watchlist: Watchlist
) -> list[tuple[str, float]]:
    """Rank layers by aggregate signal confidence (desc). Layers with no score omitted."""
    layer_of = {e.ticker: e.layer for e in watchlist.entries}
    scores: dict[str, float] = defaultdict(float)
    for s in signals:
        layer = layer_of.get(s.ticker)
        if layer is None:
            continue
        scores[layer] += float(s.confidence)
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    return [(k, v) for k, v in ranked if v > 0]


def compute_context(
    signals: Sequence[SignalLike], watchlist: Watchlist, top_n: int | None = None
) -> MarketContext:
    top_n = top_n or settings.leading_layers_top_n
    ranked = layer_leadership(signals, watchlist)
    leading = frozenset(k for k, _ in ranked[:top_n])
    return MarketContext(breadth=breadth(signals), leadership=ranked, leading_layers=leading)
