"""Option contract selection (Session 16).

A bullish signal expresses as a long call. We pick the expiry nearest a target
DTE and the strike nearest a target delta. With a live chain we use its quoted
deltas; without one we fall back to Black-Scholes deltas off a grid of strikes
around spot using the realized-vol IV. Pure given its inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as Date
from datetime import timedelta
from typing import Any

from src.core.options.pricing import bs_greeks


@dataclass(frozen=True)
class OptionContract:
    """A chosen call: strike/expiry plus the IV + delta and how it was priced."""

    option_type: str  # "call"
    strike: float
    expiry: Date
    dte: int
    iv: float
    delta: float
    source: str  # "chain" | "model"

    def to_summary(self) -> dict[str, Any]:
        return {
            "option_type": self.option_type,
            "strike": round(self.strike, 2),
            "expiry": self.expiry.isoformat(),
            "dte": self.dte,
            "iv": round(self.iv, 4),
            "delta": round(self.delta, 4),
            "source": self.source,
        }


def _from_chain(
    chain: dict[str, Any], spot: float, as_of: Date, target_delta: float, iv: float
) -> OptionContract:
    expiry: Date = chain["expiry"]
    dte = max(0, (expiry - as_of).days)
    best = min(chain["calls"], key=lambda c: abs(float(c.get("delta", 0.0)) - target_delta))
    return OptionContract(
        option_type="call",
        strike=float(best["strike"]),
        expiry=expiry,
        dte=dte,
        iv=float(best.get("iv", iv)),
        delta=float(best.get("delta", target_delta)),
        source="chain",
    )


def _from_model(
    spot: float, as_of: Date, target_delta: float, target_dte: int, iv: float, r: float
) -> OptionContract:
    expiry = as_of + timedelta(days=target_dte)
    t_years = max(target_dte, 1) / 365.0
    # Scan strikes on a +/-40% grid in 0.5% steps; keep the one whose BS delta is
    # nearest the target.
    best_strike = spot
    best_delta = 1.0
    best_gap = 1e9
    step = max(spot * 0.005, 0.01)
    k = spot * 0.6
    while k <= spot * 1.4:
        delta = bs_greeks(spot, k, t_years, r, iv, call=True)["delta"]
        gap = abs(delta - target_delta)
        if gap < best_gap:
            best_gap, best_strike, best_delta = gap, k, delta
        k += step
    return OptionContract(
        option_type="call",
        strike=round(best_strike, 2),
        expiry=expiry,
        dte=target_dte,
        iv=iv,
        delta=best_delta,
        source="model",
    )


def select_contract(
    ticker: str,
    underlying_df: Any,
    *,
    as_of: Date,
    chain: dict[str, Any] | None,
    target_delta: float,
    target_dte: int,
    iv: float,
    risk_free_rate: float = 0.04,
) -> OptionContract:
    """Choose a long call by target delta + DTE; live chain if present, else model."""
    spot = float(underlying_df["close"].iloc[-1])
    if chain is not None and chain.get("calls"):
        return _from_chain(chain, spot, as_of, target_delta, iv)
    return _from_model(spot, as_of, target_delta, target_dte, iv, risk_free_rate)
