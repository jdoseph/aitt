"""Accumulation / distribution signal tests (Session 12)."""

from __future__ import annotations

import json

from src.core import accumulation as acc
from tests.factories import make_ohlcv


def _accumulation_frame(n: int = 40) -> "object":
    """Rising closes, rising volume, closes pinned near the bar highs."""
    closes = [100.0 + i for i in range(n)]
    highs = [c + 0.2 for c in closes]  # close sits just under the high
    lows = [c - 2.0 for c in closes]
    vols = [1_000_000.0 + i * 50_000 for i in range(n)]
    return make_ohlcv(closes, highs=highs, lows=lows, volumes=vols)


def _distribution_frame(n: int = 40) -> "object":
    """Falling closes, closes pinned near the bar lows."""
    closes = [100.0 - i for i in range(n)]
    highs = [c + 2.0 for c in closes]
    lows = [c - 0.2 for c in closes]  # close sits just above the low
    vols = [1_000_000.0 + i * 50_000 for i in range(n)]
    return make_ohlcv(closes, highs=highs, lows=lows, volumes=vols)


def test_obv_rises_on_up_closes() -> None:
    df = _accumulation_frame()
    series = acc.obv(df)
    assert series.iloc[-1] > series.iloc[0]


def test_obv_falls_on_down_closes() -> None:
    df = _distribution_frame()
    series = acc.obv(df)
    assert series.iloc[-1] < series.iloc[0]


def test_up_down_volume_ratio_above_one_on_accumulation() -> None:
    assert acc.up_down_volume_ratio(_accumulation_frame()) > 1.0


def test_close_position_high_on_accumulation_low_on_distribution() -> None:
    assert acc.close_position_in_range(_accumulation_frame()) > 0.7
    assert acc.close_position_in_range(_distribution_frame()) < 0.3


def test_accumulation_score_labels() -> None:
    up = acc.accumulation_score(_accumulation_frame())
    down = acc.accumulation_score(_distribution_frame())
    assert up.label == acc.ACCUMULATION
    assert up.score > down.score
    assert down.label == acc.DISTRIBUTION
    assert up.obv_rising is True
    assert down.obv_rising is False


def test_accumulation_summary_json_serializable() -> None:
    json.dumps(acc.accumulation_score(_accumulation_frame()).to_summary())
