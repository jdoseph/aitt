"""Tests for price-level helpers (Session 7)."""

from __future__ import annotations

import pytest

from src.core import levels
from tests.factories import make_ohlcv


def test_swing_highs_detects_peaks() -> None:
    highs = [8, 12, 10, 14, 9, 8, 7]  # peaks at 12 and 14, then monotone down
    df = make_ohlcv([h - 0.5 for h in highs], highs=highs, lows=[h - 1 for h in highs])
    assert sorted(levels.swing_highs(df, k=1)) == [12.0, 14.0]


def test_swing_lows_detects_troughs() -> None:
    lows = [22, 18, 20, 16, 21, 22, 23]  # troughs at 18 and 16, then monotone up
    df = make_ohlcv([low + 0.5 for low in lows], highs=[low + 1 for low in lows], lows=lows)
    assert sorted(levels.swing_lows(df, k=1)) == [16.0, 18.0]


def test_nearest_resistance_above_price() -> None:
    highs = [10, 12, 10, 14, 10, 11, 10]
    df = make_ohlcv([h - 0.5 for h in highs], highs=highs, lows=[h - 1 for h in highs])
    assert levels.nearest_resistance(df, 11.0, lookback=50, k=1) == 12.0
    assert levels.nearest_resistance(df, 13.0, lookback=50, k=1) == 14.0
    assert levels.nearest_resistance(df, 15.0, lookback=50, k=1) is None  # blue sky


def test_nearest_support_below_price() -> None:
    lows = [20, 18, 20, 16, 20, 19, 20]
    df = make_ohlcv([low + 0.5 for low in lows], highs=[low + 1 for low in lows], lows=lows)
    assert levels.nearest_support(df, 19.0, lookback=50, k=1) == 18.0
    assert levels.nearest_support(df, 17.0, lookback=50, k=1) == 16.0
    assert levels.nearest_support(df, 15.0, lookback=50, k=1) is None


def test_suggested_stop_uses_support_then_fallback() -> None:
    lows = [20, 18, 20, 16, 20, 19, 20]
    df = make_ohlcv([low + 0.5 for low in lows], highs=[low + 1 for low in lows], lows=lows)
    # price 19 -> nearest support 18 -> stop just under it
    assert levels.suggested_stop(df, 19.0, lookback=50, k=1) == pytest.approx(18.0 * 0.99)
    # price 15 -> no support below -> fallback 8%
    assert levels.suggested_stop(df, 15.0, lookback=50, k=1, fallback_pct=8.0) == pytest.approx(
        15.0 * 0.92
    )


def test_risk_reward_math_and_guards() -> None:
    assert levels.risk_reward(100, 90, 130) == pytest.approx(3.0)  # reward 30 / risk 10
    assert levels.risk_reward(100, 90, None) is None
    assert levels.risk_reward(100, 100, 130) is None  # zero risk
    assert levels.risk_reward(100, 90, 100) is None  # zero reward
    assert levels.risk_reward(100, 110, 130) is None  # stop above entry
