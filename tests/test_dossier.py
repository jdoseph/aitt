"""Trade due-diligence dossier tests (Session 9)."""

from __future__ import annotations

import json

from src.core import levels
from src.core.dossier import DossierContext, build_dossier
from src.core.indicators import compute_metrics
from src.core.scorecard import FAIL, PASS, WARN, Check, Scorecard
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
