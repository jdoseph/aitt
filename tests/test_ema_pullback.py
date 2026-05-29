"""EMA Pullback strategy tests (Session 2)."""

from __future__ import annotations

from src.core.strategies import ema_pullback as ep
from src.core.strategies.base import INSUFFICIENT_DATA
from tests.factories import make_ohlcv

STRAT = ep.EMAPullbackStrategy()


def test_insufficient_data_below_min_bars() -> None:
    df = make_ohlcv([100.0] * 10)  # < 21
    sig = STRAT.evaluate("TEST", df)
    assert sig.status == INSUFFICIENT_DATA
    assert sig.is_actionable is False


def test_at_21_ema_touch() -> None:
    # Flat history pins both EMAs at 100; final bar dips through ~100 intrabar.
    closes = [100.0] * 29 + [100.5]
    highs = [100.5] * 29 + [101.0]
    lows = [99.5] * 29 + [99.5]
    df = make_ohlcv(closes, highs=highs, lows=lows)
    sig = STRAT.evaluate("TEST", df)
    assert sig.status == ep.AT_21_EMA


def test_extended_when_far_above_21_ema() -> None:
    closes = [100.0 * (1.01**i) for i in range(60)]  # steady 1%/day climb
    df = make_ohlcv(closes)
    sig = STRAT.evaluate("TEST", df)
    assert sig.status == ep.EXTENDED
    assert sig.details["dist_ema_21_pct"] > 8.0


def test_below_21_ema_when_whole_bar_below() -> None:
    closes = [100.0] * 25 + [96.0]
    highs = [100.5] * 25 + [97.0]
    lows = [99.5] * 25 + [95.0]
    df = make_ohlcv(closes, highs=highs, lows=lows)
    sig = STRAT.evaluate("TEST", df)
    assert sig.status == ep.BELOW_21_EMA


def test_details_carry_trend_filter_flag() -> None:
    closes = [100.0] * 60
    df = make_ohlcv(closes)
    sig = STRAT.evaluate("TEST", df)
    assert "trend_ok" in sig.details
    assert sig.details["ema_50"] is not None  # 60 bars >= 50


def test_strategy_name_propagates() -> None:
    sig = STRAT.evaluate("test", make_ohlcv([100.0] * 30))
    assert sig.strategy_name == "ema_pullback"
    assert sig.ticker == "TEST"
