"""IPO Base strategy tests (Session 3) — synthetic data."""

from __future__ import annotations

from src.core.strategies import ipo_base as ib
from src.core.strategies.base import NO_SIGNAL
from tests.factories import make_ohlcv

STRAT = ib.IPOBaseStrategy()


def test_no_signal_for_seasoned_stock() -> None:
    sig = STRAT.evaluate("T", make_ohlcv([100.0] * 70))  # >= 60 bars
    assert sig.status == NO_SIGNAL
    assert sig.is_actionable is False


def test_ipo_fresh_too_early() -> None:
    sig = STRAT.evaluate("T", make_ohlcv([100.0] * 3))  # < 5 bars
    assert sig.status == ib.IPO_FRESH


def _ipo_frame(last_close: float, last_vol: float = 1_000_000.0):
    # First 5 bars set the IPO high (~100), then a base in the mid-90s.
    highs = [100.0] * 5 + [96.0] * 14
    closes = [99.0] * 5 + [95.0] * 14
    vols = [1_000_000.0] * 19
    highs.append(max(last_close * 1.001, last_close))
    closes.append(last_close)
    vols.append(last_vol)
    return make_ohlcv(closes, highs=highs, volumes=vols)


def test_ipo_breakout_on_volume() -> None:
    sig = STRAT.evaluate("T", _ipo_frame(101.0, last_vol=3_000_000.0))
    assert sig.status == ib.IPO_BREAKOUT
    assert sig.details["ipo_high"] == 100.0
    assert sig.confidence == 2  # IPO_BREAKOUT base score


def test_ipo_basing_below_high() -> None:
    sig = STRAT.evaluate("T", _ipo_frame(97.0))
    assert sig.status == ib.IPO_BASING


def test_ipo_failed_on_deep_drawdown() -> None:
    sig = STRAT.evaluate("T", _ipo_frame(70.0))  # ~30% below IPO high
    assert sig.status == ib.IPO_FAILED


def test_breakout_needs_volume() -> None:
    # Above IPO high but ordinary volume -> still basing, not a breakout.
    sig = STRAT.evaluate("T", _ipo_frame(101.0, last_vol=1_000_000.0))
    assert sig.status == ib.IPO_BASING
