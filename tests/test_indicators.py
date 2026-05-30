"""Indicator tests (Session 2)."""

from __future__ import annotations

import pandas as pd
import pytest

from src.core import indicators as ind
from tests.factories import make_ohlcv


def test_ema_matches_pandas_ewm() -> None:
    s = pd.Series([1.0, 2, 3, 4, 5, 6, 7, 8, 9, 10])
    expected = s.ewm(span=3, adjust=False).mean()
    pd.testing.assert_series_equal(ind.ema(s, 3), expected)


def test_ema_of_constant_is_constant() -> None:
    s = pd.Series([50.0] * 30)
    assert ind.ema(s, 9).iloc[-1] == pytest.approx(50.0)


def test_add_emas_adds_columns() -> None:
    df = make_ohlcv([100.0] * 60)
    out = ind.add_emas(df)
    assert {"ema_9", "ema_21", "ema_50"} <= set(out.columns)
    assert out["ema_21"].iloc[-1] == pytest.approx(100.0)


def test_metrics_ema_200_and_alignment() -> None:
    # 260 rising bars -> price above both the 50 and 200 EMA.
    df = make_ohlcv([100.0 + i for i in range(260)])
    m = ind.compute_metrics(df)
    assert m.ema_200 is not None
    assert m.dist_ema_200_pct is not None and m.dist_ema_200_pct > 0
    assert m.above_50_ema is True
    assert m.above_200_ema is True


def test_metrics_ema_200_none_when_thin() -> None:
    m = ind.compute_metrics(make_ohlcv([100.0] * 60))  # < 200 bars
    assert m.ema_200 is None
    assert m.dist_ema_200_pct is None
    assert m.above_200_ema is None


def test_distance_pct_sign() -> None:
    assert ind.distance_pct(110, 100) == pytest.approx(10.0)
    assert ind.distance_pct(90, 100) == pytest.approx(-10.0)
    assert ind.distance_pct(5, 0) == 0.0  # guard against div-by-zero


def test_all_time_high_value_and_bars_since() -> None:
    # high peaks at 120 on the 3rd-from-last bar.
    highs = [100, 105, 110, 120, 115, 112]
    df = make_ohlcv([h - 1 for h in highs], highs=highs)
    ath, bars_since = ind.all_time_high(df)
    assert ath == 120
    assert bars_since == 2  # two bars after the peak


def test_all_time_high_uses_last_occurrence_for_freshness() -> None:
    highs = [120, 110, 120, 110]  # tie at the start and the middle
    df = make_ohlcv([h - 1 for h in highs], highs=highs)
    ath, bars_since = ind.all_time_high(df)
    assert ath == 120
    assert bars_since == 1  # most recent 120 is at index 2 (1 bar from end)


def test_compute_metrics_emas_none_when_thin() -> None:
    df = make_ohlcv([100.0] * 10)  # <21 bars
    m = ind.compute_metrics(df)
    assert m.ema_9 is not None  # 10 >= 9
    assert m.ema_21 is None
    assert m.ema_50 is None
    assert m.above_50_ema is None


def test_compute_metrics_pullback_pct() -> None:
    highs = [100.0] * 30
    closes = [99.0] * 29 + [93.0]  # last close 7% below ATH of 100
    df = make_ohlcv(closes, highs=highs)
    m = ind.compute_metrics(df)
    assert m.ath == pytest.approx(100.0)
    assert m.pullback_from_ath_pct == pytest.approx(7.0)


def test_compute_metrics_vol_ratio() -> None:
    closes = [100.0] * 25
    vols = [1_000_000.0] * 24 + [2_000_000.0]
    df = make_ohlcv(closes, volumes=vols)
    m = ind.compute_metrics(df)
    assert m.vol_ratio > 1.0  # last volume above its trailing average
