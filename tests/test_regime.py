"""Canonical market-regime gate tests (Session 10)."""

from __future__ import annotations

from src.core import regime as rg
from src.core.regime import NEUTRAL, RISK_OFF, RISK_ON
from tests.factories import make_ohlcv


def _up() -> object:
    return make_ohlcv([100.0 + i for i in range(60)])  # above its 50 EMA


def _down() -> object:
    return make_ohlcv([160.0 - i for i in range(60)])  # below its 50 EMA


def test_all_above_is_risk_on() -> None:
    r = rg.market_regime({"SPY": _up(), "QQQ": _up(), "SMH": _up()})
    assert r.label == RISK_ON
    assert r.is_risk_on and not r.is_risk_off
    assert r.n_below == 0


def test_two_below_is_risk_off() -> None:
    r = rg.market_regime({"SPY": _down(), "QQQ": _down(), "SMH": _up()})
    assert r.label == RISK_OFF
    assert r.is_risk_off
    assert r.n_below == 2


def test_one_below_is_neutral() -> None:
    r = rg.market_regime({"SPY": _down(), "QQQ": _up(), "SMH": _up()})
    assert r.label == NEUTRAL


def test_custom_risk_off_threshold() -> None:
    # With a threshold of 1, a single index below flips to RISK_OFF.
    r = rg.market_regime({"SPY": _down(), "QQQ": _up(), "SMH": _up()}, risk_off_fails=1)
    assert r.label == RISK_OFF


def test_empty_benchmarks_neutral() -> None:
    r = rg.market_regime({})
    assert r.label == NEUTRAL
    assert r.flags == {}


def test_thin_history_skipped() -> None:
    r = rg.market_regime({"SPY": make_ohlcv([100.0] * 10)})  # < 50 bars -> skipped
    assert r.flags == {}
    assert r.label == NEUTRAL


def test_summary_and_badge() -> None:
    r = rg.market_regime({"SPY": _down(), "QQQ": _down(), "SMH": _up()})
    assert "RISK_OFF" in r.badge()
    assert "below 50 EMA" in r.summary()
