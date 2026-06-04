"""Black-Scholes price, greeks, and IV solver (Session 16)."""

from __future__ import annotations

import math

import pytest

from src.core.options import pricing as p


def test_bs_call_price_known_value() -> None:
    # S=100, K=100, T=1y, r=0, sigma=0.20 -> ~7.9656 (textbook ATM value).
    price = p.bs_price(100.0, 100.0, 1.0, 0.0, 0.20, call=True)
    assert price == pytest.approx(7.9656, abs=1e-3)


def test_put_call_parity() -> None:
    S, K, T, r, sig = 100.0, 90.0, 0.5, 0.03, 0.25
    call = p.bs_price(S, K, T, r, sig, call=True)
    put = p.bs_price(S, K, T, r, sig, call=False)
    # C - P == S - K*exp(-rT)
    assert call - put == pytest.approx(S - K * math.exp(-r * T), abs=1e-9)


def test_call_delta_in_unit_interval_and_itm_above_half() -> None:
    g = p.bs_greeks(110.0, 100.0, 0.5, 0.03, 0.25, call=True)
    assert 0.5 < g["delta"] < 1.0
    assert g["theta"] < 0.0  # long option bleeds time value
    assert g["vega"] > 0.0


def test_zero_time_price_is_intrinsic() -> None:
    assert p.bs_price(120.0, 100.0, 0.0, 0.03, 0.25, call=True) == pytest.approx(20.0)
    assert p.bs_price(90.0, 100.0, 0.0, 0.03, 0.25, call=True) == pytest.approx(0.0)


def test_implied_vol_round_trip() -> None:
    S, K, T, r, sig = 100.0, 105.0, 0.4, 0.02, 0.35
    price = p.bs_price(S, K, T, r, sig, call=True)
    solved = p.implied_vol(price, S, K, T, r, call=True)
    assert solved == pytest.approx(0.35, abs=1e-3)


from datetime import date

from src.core.options.contracts import OptionContract


def _contract(source: str) -> OptionContract:
    return OptionContract(
        option_type="call", strike=95.0, expiry=date(2024, 4, 19),
        dte=45, iv=0.30, delta=0.60, source=source,
    )


def test_entry_premium_model_path_uses_black_scholes() -> None:
    c = _contract("model")
    prem, src = p.entry_premium(
        c, underlying=100.0, on=date(2024, 3, 5), chain=None, risk_free_rate=0.04
    )
    assert src == "model"
    assert prem > 5.0


def test_entry_premium_chain_path_uses_mid() -> None:
    c = _contract("chain")
    chain = {"expiry": date(2024, 4, 19),
             "calls": [{"strike": 95.0, "bid": 7.0, "ask": 7.4, "iv": 0.33, "open_interest": 500}]}
    prem, src = p.entry_premium(
        c, underlying=100.0, on=date(2024, 3, 5), chain=chain, risk_free_rate=0.04
    )
    assert src == "chain"
    assert prem == pytest.approx(7.2)  # (7.0 + 7.4)/2
