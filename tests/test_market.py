"""Tests for breadth + layer leadership (Session 7)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

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


# --- Session 11: layer strength / rotation / thesis ------------------------ #
def test_layer_strength_bullish_layer_scores_higher() -> None:
    wl = _watchlist()
    sigs = [
        _sig("NVDA", "BELOW_21_EMA", 1),  # layer1 bearish
        _sig("ANET", "BREAKOUT", 3),  # layer4 strong bullish
        _sig("CRDO", "ENTRY_ZONE", 2),  # layer4 bullish
    ]
    strength = market.layer_strength(sigs, wl)
    assert strength["layer4"] > strength["layer1"]
    assert 0.0 <= strength["layer1"] <= 100.0
    assert strength["layer4"] > 80.0  # high-confidence bullish names


def test_layer_rotation_delta_and_arrow() -> None:
    rot = market.layer_rotation({"layer4": 70.0, "layer1": 40.0}, {"layer4": 50.0, "layer1": 55.0})
    assert rot["layer4"] == pytest.approx(20.0)
    assert rot["layer1"] == pytest.approx(-15.0)
    assert market.rotation_arrow(rot["layer4"]) == "▲"
    assert market.rotation_arrow(rot["layer1"]) == "▼"
    assert market.rotation_arrow(0.0) == "▬"


def test_thesis_health_flips_when_leaders_lose_50ema() -> None:
    healthy = market.thesis_health({"NVDA": True, "AVGO": True, "VRT": False})
    assert healthy.label == market.HEALTHY
    assert healthy.holding == 2 and healthy.total == 3

    weak = market.thesis_health({"NVDA": False, "AVGO": False, "VRT": True})
    assert weak.label == market.DETERIORATING

    unknown = market.thesis_health({"NVDA": None, "AVGO": None})
    assert unknown.total == 0
    assert "unknown" in unknown.summary()
