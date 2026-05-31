"""Paper-portfolio state, NAV, and rebalancing (Session 13).

A simulated book — cash plus share positions valued at the latest closes. It
records target-weight rebalances against a hypothetical balance and never
executes a live order. Turnover costs are intentionally absent here; they're
applied in the Session 14 walk-forward backtest.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from src.core.config import settings


@dataclass
class Position:
    """A held lot: share count and the (paper) average entry price."""

    ticker: str
    shares: float
    entry: float  # average entry price (for display / P&L; not used in NAV)

    def market_value(self, price: float) -> float:
        return self.shares * price


@dataclass
class PaperPortfolio:
    """Cash + positions, valued at the latest closes. Paper-only."""

    cash: float
    positions: dict[str, Position] = field(default_factory=dict)

    @classmethod
    def empty(cls, start_balance: float | None = None) -> "PaperPortfolio":
        bal = settings.paper_start_balance if start_balance is None else start_balance
        return cls(cash=bal, positions={})

    def nav(self, prices: Mapping[str, float]) -> float:
        """Net asset value = cash + market value of all positions at ``prices``."""
        invested = sum(
            p.market_value(prices[t]) for t, p in self.positions.items() if t in prices
        )
        return self.cash + invested

    def current_weights(self, prices: Mapping[str, float]) -> dict[str, float]:
        """Each position's fraction of NAV (cash is the implicit remainder)."""
        total = self.nav(prices)
        if total <= 0:
            return {}
        return {
            t: p.market_value(prices[t]) / total
            for t, p in self.positions.items()
            if t in prices
        }

    def apply_targets(
        self, targets: Mapping[str, float], prices: Mapping[str, float]
    ) -> None:
        """Rebalance (paper) so each target ticker holds ``weight * NAV`` in value.

        Costless: NAV is conserved across the rebalance. Names absent from
        ``targets`` are fully sold back to cash. ``targets`` are fractions of NAV
        (their sum is the invested fraction; the remainder stays in cash).
        """
        total = self.nav(prices)
        new_positions: dict[str, Position] = {}
        invested = 0.0
        for ticker, weight in targets.items():
            price = prices.get(ticker)
            if price is None or price <= 0 or weight <= 0:
                continue
            value = weight * total
            shares = value / price
            # Keep the original entry for a name we already held; otherwise mark
            # entry at the current price (paper average).
            prior = self.positions.get(ticker)
            entry = prior.entry if prior is not None else price
            new_positions[ticker] = Position(ticker=ticker, shares=shares, entry=entry)
            invested += value
        self.positions = new_positions
        self.cash = total - invested

    # --- serialization (for storage) -------------------------------------- #
    def to_dict(self) -> dict[str, Any]:
        return {
            "cash": self.cash,
            "positions": [
                {"ticker": p.ticker, "shares": p.shares, "entry": p.entry}
                for p in self.positions.values()
            ],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PaperPortfolio":
        positions = {
            p["ticker"]: Position(ticker=p["ticker"], shares=p["shares"], entry=p["entry"])
            for p in data.get("positions", [])
        }
        return cls(cash=float(data.get("cash", 0.0)), positions=positions)
