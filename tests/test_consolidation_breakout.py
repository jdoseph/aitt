"""Consolidation Breakout strategy tests (Session 3) — synthetic data."""

from __future__ import annotations

from src.core.strategies import consolidation_breakout as cb
from src.core.strategies.base import INSUFFICIENT_DATA
from tests.factories import make_ohlcv

STRAT = cb.ConsolidationBreakoutStrategy()


def test_breakout_on_volume() -> None:
    # 15 tight bars (~1% range) then a gap up on 2.5x volume.
    closes = [100.0] * 15 + [105.0]
    vols = [1_000_000.0] * 15 + [2_500_000.0]
    sig = STRAT.evaluate("T", make_ohlcv(closes, volumes=vols))
    assert sig.status == cb.BREAKOUT
    assert sig.details["days_in_range"] >= 10
    assert sig.details["vol_confirm"] is True
    assert sig.confidence == 2  # BREAKOUT base score; volume already confirms


def test_breakout_needs_volume() -> None:
    # Same price breakout but ordinary volume -> not a confirmed breakout.
    closes = [100.0] * 15 + [105.0]
    vols = [1_000_000.0] * 16
    sig = STRAT.evaluate("T", make_ohlcv(closes, volumes=vols))
    assert sig.status == cb.CONSOLIDATING
    assert sig.details["unconfirmed_breakout"] is True


def test_consolidating_inside_range() -> None:
    closes = [100.0] * 15 + [100.2]
    sig = STRAT.evaluate("T", make_ohlcv(closes))
    assert sig.status == cb.CONSOLIDATING


def test_breakdown_on_volume() -> None:
    closes = [100.0] * 15 + [94.0]
    vols = [1_000_000.0] * 15 + [2_500_000.0]
    sig = STRAT.evaluate("T", make_ohlcv(closes, volumes=vols))
    assert sig.status == cb.BREAKDOWN
    assert sig.details["vol_confirm"] is True


def test_no_pattern_when_trending() -> None:
    # Strong 2%/day trend never forms a tight multi-day base.
    closes = [100.0 * (1.02**i) for i in range(20)]
    sig = STRAT.evaluate("T", make_ohlcv(closes))
    assert sig.status == cb.NO_PATTERN


def test_insufficient_data() -> None:
    sig = STRAT.evaluate("T", make_ohlcv([100.0] * 5))
    assert sig.status == INSUFFICIENT_DATA
