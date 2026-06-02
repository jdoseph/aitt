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
