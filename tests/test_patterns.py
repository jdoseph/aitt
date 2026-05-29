"""Pattern detection + confidence scoring tests (Session 2)."""

from __future__ import annotations

from src.core import patterns
from src.core.patterns import PatternHit, detect_bullish_patterns, score_confidence
from tests.factories import make_ohlcv


def _hit(name: str) -> PatternHit:
    strength = next(s for n, (_, s) in patterns._PATTERN_FUNCS.items() if n == name)
    return PatternHit(name=name, strength=strength, bar_offset=0)


# --- detection ------------------------------------------------------------- #
def test_detect_bullish_engulfing() -> None:
    # Prior bearish candle then a larger bullish candle that engulfs it.
    opens = [101, 100, 101, 100, 101, 100, 101, 100, 100.0, 94.0]
    closes = [100, 101, 100, 101, 100, 101, 100, 101, 95.0, 102.0]
    highs = [o + 0.5 if o > c else c + 0.5 for o, c in zip(opens, closes)]
    lows = [c - 0.5 if o > c else o - 0.5 for o, c in zip(opens, closes)]
    df = make_ohlcv(closes, opens=opens, highs=highs, lows=lows)
    names = {h.name for h in detect_bullish_patterns(df)}
    assert "bullish_engulfing" in names


def test_detect_returns_empty_for_too_few_bars() -> None:
    df = make_ohlcv([100.0])
    assert detect_bullish_patterns(df) == []


def test_detect_respects_lookback_window() -> None:
    # Engulfing is flagged on its second candle (index 6, 3 bars from the end),
    # followed by plain red candles. A 3-bar window excludes it; a 6-bar finds it.
    opens = [101, 100, 101, 100, 101, 100.0, 94.0, 101.5, 101.0, 100.5]
    closes = [100, 101, 100, 101, 100, 95.0, 102.0, 101.0, 100.5, 100.0]
    highs = [max(o, c) + 0.2 for o, c in zip(opens, closes)]
    lows = [min(o, c) - 0.2 for o, c in zip(opens, closes)]
    df = make_ohlcv(closes, opens=opens, highs=highs, lows=lows)
    assert all(h.name != "bullish_engulfing" for h in detect_bullish_patterns(df, lookback=3))
    assert any(h.name == "bullish_engulfing" for h in detect_bullish_patterns(df, lookback=6))


# --- confidence scoring (pure) --------------------------------------------- #
def test_score_at_ema_with_strong_pattern_is_three_stars() -> None:
    assert score_confidence("AT_21_EMA", [_hit("bullish_engulfing")]) == 3


def test_score_at_ema_alone_is_one_star() -> None:
    assert score_confidence("AT_21_EMA", []) == 1


def test_score_at_ema_with_moderate_pattern_is_two_stars() -> None:
    assert score_confidence("AT_9_EMA", [_hit("hammer")]) == 2


def test_pattern_confirmation_beats_no_pattern() -> None:
    confirmed = score_confidence("ENTRY_ZONE", [_hit("morning_star")])
    bare = score_confidence("ENTRY_ZONE", [])
    assert confirmed > bare


def test_non_actionable_status_scores_zero_even_with_pattern() -> None:
    assert score_confidence("EXTENDED", [_hit("bullish_engulfing")]) == 0
    assert score_confidence("CORRECTION", [_hit("hammer")]) == 0


def test_breakout_base_is_two_and_caps_at_three() -> None:
    assert score_confidence("BREAKOUT", []) == 2
    assert score_confidence("BREAKOUT", [_hit("bullish_engulfing")]) == 3


def test_doji_counts_only_at_support() -> None:
    # ENTRY_ZONE is a support status -> doji adds a star.
    assert score_confidence("ENTRY_ZONE", [_hit("doji")]) == 2
    # BREAKOUT is actionable but not a "support" status -> doji adds nothing.
    assert score_confidence("BREAKOUT", [_hit("doji")]) == 2
