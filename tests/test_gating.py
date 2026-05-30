"""Automatic disqualifier + regime-gate tests (Session 10)."""

from __future__ import annotations

from src.core.config import Settings
from src.core.gating import disqualifiers
from src.core.regime import RISK_OFF, RISK_ON, Regime
from src.core.scorecard import FAIL, PASS, WARN, Check, Scorecard
from src.core.signals import SignalEngine
from src.core.storage import Storage
from src.core.strategies.base import Signal

SIG = Signal("T", "ema_pullback", "AT_21_EMA", confidence=3)


def _card(*checks: Check, action: str = "DECENT") -> Scorecard:
    return Scorecard(checks=list(checks), score=0.0, action=action)


def _regime(label: str = RISK_ON) -> Regime:
    return Regime(label=label, flags={"SPY": label != RISK_OFF}, span=50)


# --- individual rules ------------------------------------------------------ #
def test_below_50ema_trips() -> None:
    out = disqualifiers(SIG, _card(Check("trend", FAIL, "below 50 EMA")), _regime())
    assert "price below the 50 EMA" in out


def test_earnings_within_window_trips() -> None:
    card = _card(Check("earnings", WARN, "2d away", num=2.0))
    out = disqualifiers(SIG, card, _regime())
    assert any("earnings in 2d" in r for r in out)


def test_earnings_outside_window_clean() -> None:
    card = _card(Check("earnings", PASS, "10d away", num=10.0))
    assert disqualifiers(SIG, card, _regime()) == []


def test_rs_below_market_trips() -> None:
    card = _card(Check("rel_strength", FAIL, "-5.0% vs mkt", num=-5.0))
    assert "relative strength below market" in disqualifiers(SIG, card, _regime())


def test_declining_volume_trips() -> None:
    card = _card(Check("volume", FAIL, "0.7x avg", num=0.7))
    assert "volume below its 20-day average" in disqualifiers(SIG, card, _regime())


def test_min_rr_off_by_default() -> None:
    card = _card(Check("risk_reward", WARN, "1.2 : 1", num=1.2))
    assert disqualifiers(SIG, card, _regime()) == []  # dq_min_rr=0 -> rule disabled


def test_min_rr_on_trips() -> None:
    cfg = Settings()
    cfg.dq_min_rr = 2.0
    card = _card(Check("risk_reward", WARN, "1.2 : 1", num=1.2))
    out = disqualifiers(SIG, card, _regime(), cfg=cfg)
    assert any("risk/reward" in r for r in out)


def test_toggle_off_disables_rule() -> None:
    cfg = Settings()
    cfg.dq_below_50ema = False
    card = _card(Check("trend", FAIL, "below 50 EMA"))
    assert disqualifiers(SIG, card, _regime(), cfg=cfg) == []


def test_clean_setup_has_no_disqualifiers() -> None:
    card = _card(Check("trend", PASS, "above 50 EMA"), Check("volume", PASS, "2x avg", num=2.0))
    assert disqualifiers(SIG, card, _regime()) == []


# --- gate orchestration (suppress / RISK_OFF bar) -------------------------- #
def test_gate_suppresses_below_50ema_in_suppress_mode() -> None:
    engine = SignalEngine(Storage.in_memory())
    card = _card(Check("trend", FAIL, "below 50 EMA"))
    dq, suppressed = engine._gate(SIG, card, _regime(), ("entry", "msg"))
    assert "price below the 50 EMA" in dq
    assert suppressed is True  # default disqualifier_mode == "suppress"


def test_gate_risk_off_raises_bar_for_low_confidence_buy() -> None:
    engine = SignalEngine(Storage.in_memory())
    card = _card(Check("trend", PASS, "above 50 EMA"))  # clean otherwise
    weak = Signal("T", "consolidation_breakout", "BREAKOUT", confidence=1)
    dq, suppressed = engine._gate(weak, card, _regime(RISK_OFF), ("entry", "msg"))
    assert any("RISK_OFF" in r for r in dq)
    assert suppressed is True


def test_gate_passes_clean_setup() -> None:
    engine = SignalEngine(Storage.in_memory())
    card = _card(Check("trend", PASS, "above 50 EMA"), Check("volume", PASS, "2x", num=2.0))
    dq, suppressed = engine._gate(SIG, card, _regime(RISK_ON), ("entry", "msg"))
    assert dq == []
    assert suppressed is False
