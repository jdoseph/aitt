"""Trade due-diligence dossier tests (Session 9)."""

from __future__ import annotations

import json

from src.core import levels, multitimeframe as mtf
from src.core.accumulation import AccumulationResult
from src.core.dossier import DossierContext, build_dossier
from src.core.indicators import compute_metrics
from src.core.scorecard import FAIL, PASS, WARN, Check, Scorecard
from src.core.stage import StageResult
from src.core.strategies.base import Signal
from tests.factories import make_ohlcv


def _card(action: str, *checks: Check) -> Scorecard:
    return Scorecard(checks=list(checks), score=0.0, action=action)


def _uptrend(n: int = 260) -> "object":
    return make_ohlcv([100.0 + i for i in range(n)])


# --- reasons split --------------------------------------------------------- #
def test_passes_become_bull_warnsfails_become_bear() -> None:
    df = _uptrend()
    sigs = [Signal("T", "ema_pullback", "AT_21_EMA")]
    card = _card(
        "DECENT",
        Check("trend", PASS, "above 50 EMA"),
        Check("rel_strength", FAIL, "-5.0% vs mkt"),
        Check("earnings", WARN, "3d away"),
        Check("risk_reward", PASS, "3.0 : 1"),
    )
    d = build_dossier("T", sigs, card, DossierContext(df=df, best_signal=sigs[0]))
    assert any("50 EMA" in r for r in d.reasons_to_buy)
    assert any("market" in r.lower() for r in d.reasons_not_to_buy)
    assert any("Earnings" in r for r in d.reasons_not_to_buy)
    assert d.strongest_bull is not None
    assert d.strongest_bear is not None


def test_bear_case_never_empty_on_clean_setup() -> None:
    df = _uptrend()
    sigs = [Signal("T", "ema_pullback", "AT_21_EMA")]
    card = _card("HIGH-QUALITY", Check("trend", PASS, "above 50 EMA"), Check("risk_reward", PASS, "4 : 1"))
    d = build_dossier("T", sigs, card, DossierContext(df=df, best_signal=sigs[0]))
    assert d.reasons_not_to_buy  # fallback discipline reminder is always present


# --- confluence ------------------------------------------------------------ #
def test_confluence_counts_distinct_bullish_strategies() -> None:
    df = _uptrend()
    sigs = [
        Signal("T", "ema_pullback", "AT_21_EMA"),
        Signal("T", "ath_pullback", "ENTRY_ZONE"),
        Signal("T", "consolidation_breakout", "NO_PATTERN"),  # not bullish -> excluded
    ]
    card = _card("DECENT", Check("trend", PASS, "above 50 EMA"))
    d = build_dossier("T", sigs, card, DossierContext(df=df, best_signal=sigs[0]))
    assert d.confluence == 2
    assert "EMA AT_21_EMA" in d.confluence_detail
    assert any("2/4 strategies aligned" in r for r in d.reasons_to_buy)


# --- trend alignment + regime ---------------------------------------------- #
def test_trend_alignment_uses_50_and_200_ema() -> None:
    d = build_dossier(
        "T",
        [Signal("T", "ema_pullback", "AT_21_EMA")],
        _card("DECENT", Check("trend", PASS, "x")),
        DossierContext(df=_uptrend()),
    )
    assert "50 & 200" in d.trend_alignment


def test_market_regime_reflects_qqq_smh() -> None:
    up = _uptrend()
    benches = {"QQQ": up, "SMH": up}
    d = build_dossier(
        "T",
        [Signal("T", "ema_pullback", "AT_21_EMA")],
        _card("DECENT", Check("trend", PASS, "x")),
        DossierContext(df=up, benchmarks=benches),
    )
    assert "above" in d.market_regime
    assert any("regime supportive" in r.lower() for r in d.reasons_to_buy)


# --- trade plan ------------------------------------------------------------ #
def test_sizing_tier_follows_grade() -> None:
    df = _uptrend()
    sig = Signal("T", "ema_pullback", "AT_21_EMA")
    for grade, tier in [("HIGH-QUALITY", "FULL"), ("DECENT", "HALF"), ("MARGINAL", "STARTER"), ("AVOID", "NONE")]:
        d = build_dossier("T", [sig], _card(grade, Check("trend", PASS, "x")), DossierContext(df=df, best_signal=sig))
        assert d.trade_plan.sizing_tier == tier
        assert d.trade_plan.profit_targets  # +10% / +15% suggestions present


def test_strategy_stop_differs_by_setup_type() -> None:
    df = make_ohlcv([100.0 + i for i in range(60)])
    m = compute_metrics(df)
    ema_sig = Signal("T", "ema_pullback", "AT_21_EMA")
    cons_sig = Signal("T", "consolidation_breakout", "BREAKOUT", details={"range_low": 90.0})
    ipo_sig = Signal("T", "ipo_base", "IPO_BREAKOUT", details={"ipo_high": 50.0})

    assert levels.strategy_stop(df, cons_sig, m) == round(90.0 * 0.99, 4)
    assert levels.strategy_stop(df, ipo_sig, m) == round(50.0 * 0.99, 4)
    assert m.ema_21 is not None
    assert levels.strategy_stop(df, ema_sig, m) == round(min(m.ema_21, m.close) * 0.99, 4)


def test_invalidation_text_per_strategy() -> None:
    assert levels.invalidation_text(Signal("T", "ema_pullback", "AT_21_EMA")) == "close below the 21 EMA"
    assert "base" in levels.invalidation_text(Signal("T", "consolidation_breakout", "BREAKOUT"))
    assert "swing low" in levels.invalidation_text(Signal("T", "ath_pullback", "ENTRY_ZONE"))


# --- Session 12: deeper-signal integration --------------------------------- #
def test_stage_4_caps_grade_and_adds_bear() -> None:
    df = _uptrend()
    sig = Signal("T", "ema_pullback", "AT_21_EMA")
    card = _card("HIGH-QUALITY", Check("trend", PASS, "above 50 EMA"))
    stage4 = StageResult(4, "declining", above_ma=False, slope_pct=-3.0)
    d = build_dossier("T", [sig], card, DossierContext(df=df, best_signal=sig, stage=stage4))
    assert d.grade == "MARGINAL"  # capped down from HIGH-QUALITY
    assert d.trade_plan.sizing_tier == "STARTER"
    assert any("Stage 4" in r for r in d.reasons_not_to_buy)


def test_stage_2_adds_bull_reason_without_capping() -> None:
    df = _uptrend()
    sig = Signal("T", "ema_pullback", "AT_21_EMA")
    card = _card("DECENT", Check("trend", PASS, "above 50 EMA"))
    stage2 = StageResult(2, "advancing", above_ma=True, slope_pct=3.0)
    d = build_dossier("T", [sig], card, DossierContext(df=df, best_signal=sig, stage=stage2))
    assert d.grade == "DECENT"
    assert any("Stage 2" in r for r in d.reasons_to_buy)


def test_weekly_uptrend_and_accumulation_become_bull() -> None:
    df = _uptrend()
    sig = Signal("T", "ema_pullback", "AT_21_EMA")
    card = _card("DECENT", Check("trend", PASS, "above 50 EMA"))
    wt = mtf.WeeklyTrend(mtf.UPTREND, above_ma=True, slope_pct=2.0, ma=100.0, n_weeks=40)
    acc = AccumulationResult(score=75.0, label="accumulation", obv_rising=True,
                             ad_rising=True, ud_ratio=2.0, close_pos=0.9)
    d = build_dossier("T", [sig], card,
                      DossierContext(df=df, best_signal=sig, weekly=wt, accumulation=acc))
    assert any("Weekly uptrend" in r for r in d.reasons_to_buy)
    assert any("accumulation" in r.lower() for r in d.reasons_to_buy)


def test_high_crowding_adds_bear_reason() -> None:
    # Steep, low-volatility ramp -> price sits many ATRs above a lagging 200 EMA.
    closes = [100.0 + i * 2 for i in range(260)]
    df = make_ohlcv(closes, highs=[c + 0.1 for c in closes], lows=[c - 0.1 for c in closes])
    m = compute_metrics(df)
    assert m.crowding is not None and m.crowding >= 70  # precondition for this fixture
    sig = Signal("T", "ema_pullback", "AT_21_EMA")
    d = build_dossier("T", [sig], _card("DECENT", Check("trend", PASS, "x")),
                      DossierContext(df=df, best_signal=sig))
    assert any("Crowded" in r for r in d.reasons_not_to_buy)


# --- serialization --------------------------------------------------------- #
def test_dossier_summary_is_json_serializable() -> None:
    df = _uptrend()
    sig = Signal("T", "ema_pullback", "AT_21_EMA")
    d = build_dossier("T", [sig], _card("DECENT", Check("trend", PASS, "x")), DossierContext(df=df, best_signal=sig))
    summary = d.to_summary()
    json.dumps(summary)  # must not raise
    assert summary["trade_plan"]["sizing_tier"] == "HALF"
    assert summary["grade"] == "DECENT"
    assert isinstance(summary["reasons_not_to_buy"], list)
