"""Tests for relative-strength helpers (Session 7)."""

from __future__ import annotations

import pytest

from src.core import benchmarks as bm
from tests.factories import make_ohlcv


def test_return_pct_over_lookback() -> None:
    df = make_ohlcv([100.0, 101, 102, 103, 104, 110])  # last vs 5 bars ago: 100 -> 110
    assert bm.return_pct(df, lookback=5) == pytest.approx(10.0)


def test_return_pct_too_short() -> None:
    assert bm.return_pct(make_ohlcv([100.0, 101]), lookback=5) is None


def test_relative_strength_outperform_flag() -> None:
    strong = make_ohlcv([100.0] * 5 + [115.0])  # +15% over 5 bars
    bench = make_ohlcv([100.0] * 5 + [105.0])   # +5%
    rs = bm.relative_strength(strong, bench, "SPY", lookback=5)
    assert rs is not None
    assert rs.outperform is True
    assert rs.delta == pytest.approx(10.0)


def test_relative_strength_underperform() -> None:
    weak = make_ohlcv([100.0] * 5 + [90.0])   # -10%
    bench = make_ohlcv([100.0] * 5 + [105.0])  # +5%
    rs = bm.relative_strength(weak, bench, "QQQ", lookback=5)
    assert rs is not None
    assert rs.outperform is False
    assert rs.delta == pytest.approx(-15.0)


def test_relative_strength_all_skips_missing() -> None:
    t = make_ohlcv([100.0] * 5 + [110.0])
    benches = {
        "SPY": make_ohlcv([100.0] * 5 + [105.0]),
        "QQQ": make_ohlcv([100.0, 101]),  # too short -> skipped
    }
    out = bm.relative_strength_all(t, benches, lookback=5)
    assert [rs.benchmark for rs in out] == ["SPY"]
