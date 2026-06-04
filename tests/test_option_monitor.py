"""Option marking + whichever-first exit evaluation (Session 16)."""

from __future__ import annotations

from datetime import date

import pytest

from src.core.options.option_trades import evaluate_exit, mark_premium
from src.core.storage import OptionTrade


def _open_trade(**kw) -> OptionTrade:
    base = dict(
        ticker="NVDA", status="OPEN", option_type="call", strike=95.0,
        expiry=date(2024, 4, 19), contracts=2, multiplier=100, entry_iv=0.30,
        entry_premium=7.0, entry_date=date(2024, 3, 1), underlying_entry=100.0,
        underlying_stop=90.0, underlying_target=120.0,
        tp_premium=10.5, sl_premium=3.5,
    )
    base.update(kw)
    return OptionTrade(**base)


def test_mark_premium_uses_black_scholes() -> None:
    t = _open_trade()
    prem = mark_premium(t, underlying=100.0, on=date(2024, 3, 15), iv=0.30, risk_free_rate=0.04)
    assert prem > 5.0  # ITM call with ~35 DTE has real value


def test_exit_underlying_stop() -> None:
    t = _open_trade()
    reason = evaluate_exit(t, underlying=89.0, premium=4.0, on=date(2024, 3, 15))
    assert reason == "EXIT_STOP"


def test_exit_underlying_target() -> None:
    t = _open_trade()
    reason = evaluate_exit(t, underlying=121.0, premium=9.0, on=date(2024, 3, 15))
    assert reason == "EXIT_TARGET"


def test_exit_premium_take_profit() -> None:
    t = _open_trade()
    reason = evaluate_exit(t, underlying=110.0, premium=11.0, on=date(2024, 3, 15))
    assert reason == "EXIT_OPT_TP"


def test_exit_premium_stop() -> None:
    t = _open_trade()
    reason = evaluate_exit(t, underlying=96.0, premium=3.0, on=date(2024, 3, 15))
    assert reason == "EXIT_OPT_SL"


def test_exit_min_dte() -> None:
    t = _open_trade()
    # 21-day guard: on an as-of date within 21 days of the 2024-04-19 expiry.
    reason = evaluate_exit(t, underlying=100.0, premium=7.0, on=date(2024, 4, 5))
    assert reason == "EXIT_DTE"


def test_exit_expiry() -> None:
    t = _open_trade()
    reason = evaluate_exit(t, underlying=100.0, premium=7.0, on=date(2024, 4, 19))
    assert reason == "EXIT_EXPIRY"


def test_exit_stop_priority_over_target_when_both() -> None:
    t = _open_trade()
    # Degenerate: both stop and target appear satisfied -> stop wins.
    t.underlying_stop = 120.0
    t.underlying_target = 120.0
    reason = evaluate_exit(t, underlying=120.0, premium=9.0, on=date(2024, 3, 15))
    assert reason == "EXIT_STOP"


def test_no_exit_returns_empty() -> None:
    t = _open_trade()
    assert evaluate_exit(t, underlying=105.0, premium=8.0, on=date(2024, 3, 15)) == ""
