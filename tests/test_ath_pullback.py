"""ATH Pullback strategy tests (Session 2)."""

from __future__ import annotations

from src.core.strategies import ath_pullback as ap
from tests.factories import make_ohlcv

STRAT = ap.ATHPullbackStrategy()


def _frame(last_close: float, *, ath: float = 100.0, ath_bars_from_end: int = 3, n: int = 40):
    """Build a frame whose ATH high is ``ath`` placed ``ath_bars_from_end`` bars
    from the end, ending at ``last_close``."""
    closes = [ath * 0.9] * n
    highs = [ath * 0.9 * 1.001] * n
    peak_idx = n - 1 - ath_bars_from_end
    highs[peak_idx] = ath
    closes[peak_idx] = ath * 0.999
    closes[-1] = last_close
    highs[-1] = max(last_close * 1.001, last_close)
    return make_ohlcv(closes, highs=highs)


def test_at_ath_when_near_high() -> None:
    sig = STRAT.evaluate("T", _frame(99.6, ath_bars_from_end=0))
    assert sig.status == ap.AT_ATH


def test_entry_zone_at_7pct_pullback() -> None:
    sig = STRAT.evaluate("T", _frame(93.0))
    assert sig.status == ap.ENTRY_ZONE
    assert sig.details["pullback_pct"] == 7.0
    assert sig.confidence >= 1  # ENTRY_ZONE base score is 1


def test_minor_pullback_at_3pct() -> None:
    sig = STRAT.evaluate("T", _frame(97.0))
    assert sig.status == ap.MINOR_PULLBACK


def test_deep_pullback_at_15pct() -> None:
    sig = STRAT.evaluate("T", _frame(85.0))
    assert sig.status == ap.DEEP_PULLBACK


def test_correction_beyond_20pct() -> None:
    sig = STRAT.evaluate("T", _frame(70.0))
    assert sig.status == ap.CORRECTION
    assert sig.confidence == 0  # not an actionable status


def test_ath_freshness_flag() -> None:
    fresh = STRAT.evaluate("T", _frame(93.0, ath_bars_from_end=5))
    stale = STRAT.evaluate("T", _frame(93.0, ath_bars_from_end=35, n=60))
    assert fresh.details["ath_fresh"] is True
    assert stale.details["ath_fresh"] is False
