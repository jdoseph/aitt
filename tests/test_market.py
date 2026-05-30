"""Tests for breadth + layer leadership (Session 7)."""

from __future__ import annotations

from types import SimpleNamespace

from src.core import market
from src.core.watchlist import Watchlist, WatchlistEntry


def _sig(ticker: str, status: str, confidence: int = 1) -> SimpleNamespace:
    return SimpleNamespace(ticker=ticker, status=status, confidence=confidence)


def _watchlist() -> Watchlist:
    return Watchlist(
        layers={"layer1": "GPU", "layer4": "Interconnects"},
        entries=[
            WatchlistEntry(ticker="NVDA", name="NVIDIA", layer="layer1"),
            WatchlistEntry(ticker="ANET", name="Arista", layer="layer4"),
            WatchlistEntry(ticker="CRDO", name="Credo", layer="layer4"),
        ],
    )


def test_ticker_sentiment_precedence() -> None:
    assert market.ticker_sentiment(["AT_21_EMA", "BELOW_21_EMA"]) == "bullish"  # bull wins
    assert market.ticker_sentiment(["BELOW_21_EMA", "NO_PATTERN"]) == "bearish"
    assert market.ticker_sentiment(["EXTENDED", "NO_PATTERN"]) == "neutral"


def test_breadth_counts_by_ticker() -> None:
    sigs = [
        _sig("NVDA", "AT_21_EMA"),
        _sig("NVDA", "NO_PATTERN"),  # same ticker -> still one bullish
        _sig("INTC", "BELOW_21_EMA"),
        _sig("MU", "EXTENDED"),
    ]
    b = market.breadth(sigs)
    assert (b.bullish, b.bearish, b.neutral, b.total) == (1, 1, 1, 3)


def test_breadth_healthy_threshold() -> None:
    bullish = [_sig(f"T{i}", "ENTRY_ZONE") for i in range(6)]
    bearish = [_sig(f"B{i}", "BELOW_21_EMA") for i in range(4)]
    assert market.breadth(bullish + bearish).healthy is True  # 60% bullish
    assert market.breadth(bearish).healthy is False


def test_layer_leadership_ranks_by_confidence() -> None:
    wl = _watchlist()
    sigs = [
        _sig("NVDA", "AT_21_EMA", 1),
        _sig("ANET", "BREAKOUT", 3),
        _sig("CRDO", "ENTRY_ZONE", 2),
    ]
    ctx = market.compute_context(sigs, wl, top_n=1)
    # layer4 (3+2=5) outranks layer1 (1)
    assert ctx.leadership[0][0] == "layer4"
    assert ctx.leading_layers == frozenset({"layer4"})
