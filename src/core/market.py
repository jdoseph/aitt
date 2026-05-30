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


# --------------------------------------------------------------------------- #
# Session 11: layer strength + rotation + thesis health
# --------------------------------------------------------------------------- #
def _ticker_strength_value(sentiment: str, confidence: int) -> float:
    """Per-ticker 0-1 strength: sentiment anchored, nudged by signal confidence."""
    conf = max(0, min(3, confidence)) / 3.0
    if sentiment == "bullish":
        return 0.6 + 0.4 * conf
    if sentiment == "bearish":
        return 0.2 * (1.0 - conf)
    return 0.5


def layer_strength(
    signals: Sequence[SignalLike], watchlist: Watchlist
) -> dict[str, float]:
    """A 0-100 strength per value-chain layer (mean per-ticker strength).

    Layers with no signalling tickers are omitted. Higher = more bullish signals
    at higher confidence flowing through that layer.
    """
    layer_of = {e.ticker: e.layer for e in watchlist.entries}
    by_ticker_status: dict[str, list[str]] = defaultdict(list)
    by_ticker_conf: dict[str, int] = defaultdict(int)
    for s in signals:
        by_ticker_status[s.ticker].append(s.status)
        by_ticker_conf[s.ticker] = max(by_ticker_conf[s.ticker], s.confidence)

    by_layer: dict[str, list[float]] = defaultdict(list)
    for ticker, statuses in by_ticker_status.items():
        layer = layer_of.get(ticker)
        if layer is None:
            continue
        val = _ticker_strength_value(ticker_sentiment(statuses), by_ticker_conf[ticker])
        by_layer[layer].append(val)
    return {layer: sum(vals) / len(vals) * 100.0 for layer, vals in by_layer.items() if vals}


def layer_rotation(
    current: dict[str, float], prior: dict[str, float]
) -> dict[str, float]:
    """Δ in layer strength vs a prior window (positive = money rotating in)."""
    layers = set(current) | set(prior)
    return {layer: current.get(layer, 0.0) - prior.get(layer, 0.0) for layer in layers}


def rotation_arrow(delta: float, flat_eps: float = 1.0) -> str:
    """A ▲ / ▼ / ▬ glyph for a rotation delta."""
    if delta > flat_eps:
        return "▲"
    if delta < -flat_eps:
        return "▼"
    return "▬"


HEALTHY, DETERIORATING = "Healthy", "Deteriorating"


@dataclass(frozen=True)
class ThesisHealth:
    label: str  # Healthy | Deteriorating
    holding: int  # leaders above their 50 EMA
    total: int  # leaders with a known 50-EMA read

    def summary(self) -> str:
        if self.total == 0:
            return "thesis unknown"
        return f"{self.label} ({self.holding}/{self.total} leaders above 50 EMA)"


def thesis_health(above_50_by_leader: dict[str, bool | None]) -> ThesisHealth:
    """AI-thesis health from whether the key leaders hold their 50 EMA.

    ``Healthy`` when a majority of leaders with a known read are above their
    50 EMA; ``Deteriorating`` otherwise. Unknown reads are ignored.
    """
    known = {k: v for k, v in above_50_by_leader.items() if v is not None}
    total = len(known)
    holding = sum(1 for v in known.values() if v)
    if total == 0:
        return ThesisHealth(DETERIORATING, 0, 0)
    label = HEALTHY if holding * 2 >= total else DETERIORATING
    return ThesisHealth(label, holding, total)
