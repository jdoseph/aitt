"""Black-Scholes pricing, greeks, and an implied-vol solver (Session 16).

Pure functions, no I/O. ``T`` is in years; ``sigma``/``r`` are annualized.
Greeks are per-1.0-of-underlying and per-1-year for theta (callers convert to
per-day for display). Used for every option mark and the entire backtest; the
live chain is only consulted at entry (see chain.py).
"""

from __future__ import annotations

import math


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _d1_d2(S: float, K: float, T: float, r: float, sigma: float) -> tuple[float, float]:
    vol_t = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / vol_t
    return d1, d1 - vol_t


def bs_price(S: float, K: float, T: float, r: float, sigma: float, *, call: bool = True) -> float:
    """Black-Scholes price. Degenerate inputs (T<=0 or sigma<=0) return intrinsic."""
    if T <= 0.0 or sigma <= 0.0 or S <= 0.0 or K <= 0.0:
        intrinsic = (S - K) if call else (K - S)
        return max(0.0, intrinsic)
    d1, d2 = _d1_d2(S, K, T, r, sigma)
    if call:
        return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
    return K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def bs_greeks(
    S: float, K: float, T: float, r: float, sigma: float, *, call: bool = True
) -> dict[str, float]:
    """Delta, gamma, vega (per 1.00 vol), theta (per year), rho. Intrinsic edge -> zeros."""
    if T <= 0.0 or sigma <= 0.0 or S <= 0.0 or K <= 0.0:
        delta = (1.0 if S > K else 0.0) if call else (-1.0 if S < K else 0.0)
        return {"delta": delta, "gamma": 0.0, "vega": 0.0, "theta": 0.0, "rho": 0.0}
    d1, d2 = _d1_d2(S, K, T, r, sigma)
    pdf = _norm_pdf(d1)
    gamma = pdf / (S * sigma * math.sqrt(T))
    vega = S * pdf * math.sqrt(T)
    if call:
        delta = _norm_cdf(d1)
        theta = -(S * pdf * sigma) / (2.0 * math.sqrt(T)) - r * K * math.exp(-r * T) * _norm_cdf(d2)
        rho = K * T * math.exp(-r * T) * _norm_cdf(d2)
    else:
        delta = _norm_cdf(d1) - 1.0
        theta = -(S * pdf * sigma) / (2.0 * math.sqrt(T)) + r * K * math.exp(-r * T) * _norm_cdf(-d2)
        rho = -K * T * math.exp(-r * T) * _norm_cdf(-d2)
    return {"delta": delta, "gamma": gamma, "vega": vega, "theta": theta, "rho": rho}


def implied_vol(
    price: float, S: float, K: float, T: float, r: float, *, call: bool = True,
    lo: float = 1e-4, hi: float = 5.0, tol: float = 1e-6, max_iter: int = 100,
) -> float | None:
    """Solve for sigma via bisection (robust). None if the price is below intrinsic."""
    if T <= 0.0 or price <= 0.0:
        return None
    intrinsic = max(0.0, (S - K) if call else (K - S))
    if price < intrinsic - tol:
        return None
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        diff = bs_price(S, K, T, r, mid, call=call) - price
        if abs(diff) < tol:
            return mid
        if diff > 0.0:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)
