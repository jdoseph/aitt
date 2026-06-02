"""Option paper-book lifecycle + accounting (Session 16).

The options analogue of Session 15's ``PaperBook``. Positions are long calls held
in whole contracts (× ``multiplier`` shares). Premiums are per share; dollar P&L
multiplies by contracts × multiplier. Budget accounting mirrors PaperBook: spendable
cash = budget − OPEN/PENDING cost + realized P&L. All fake money.
"""

from __future__ import annotations

import json
import math
from datetime import date as Date
from typing import Any

from src.core.config import settings
from src.core.options.contracts import OptionContract
from src.core.storage import OptionTrade, Storage


class OptionBook:
    """The autonomous options paper account: lifecycle + budget + sizing + NAV."""

    def __init__(self, storage: Storage, *, budget: float | None = None) -> None:
        self.storage = storage
        self.budget = budget if budget is not None else settings.paper_budget

    # --- queries ---------------------------------------------------------- #
    def pending_trades(self) -> list[OptionTrade]:
        return self.storage.get_option_trades(status="PENDING")

    def open_trades(self) -> list[OptionTrade]:
        return self.storage.get_option_trades(status="OPEN")

    def closed_trades(self) -> list[OptionTrade]:
        return self.storage.get_option_trades(status="CLOSED")

    def has_active(self, ticker: str) -> bool:
        ticker = ticker.upper()
        return any(t.ticker == ticker for t in (*self.pending_trades(), *self.open_trades()))

    # --- cash accounting -------------------------------------------------- #
    def _committed_cost(self, *, include_pending: bool) -> float:
        statuses = ("OPEN", "PENDING") if include_pending else ("OPEN",)
        total = 0.0
        for status in statuses:
            total += sum(t.cost_basis for t in self.storage.get_option_trades(status=status))
        return total

    def _realized_pnl(self) -> float:
        return sum(t.pnl_dollars for t in self.closed_trades())

    def available_cash(self) -> float:
        cash = self.budget - self._committed_cost(include_pending=True) + self._realized_pnl()
        return max(0.0, cash)

    def _nav_cash(self) -> float:
        return self.budget - self._committed_cost(include_pending=False) + self._realized_pnl()

    def invested_value(self, marks: dict[int, float]) -> float:
        """Market value of OPEN positions; ``marks`` maps trade_id -> current premium."""
        total = 0.0
        for t in self.open_trades():
            prem = marks.get(t.trade_id or -1, t.entry_premium)
            total += prem * t.contracts * t.multiplier
        return total

    def current_nav(self, marks: dict[int, float]) -> float:
        return self._nav_cash() + self.invested_value(marks)

    def voo_nav(self, voo_start_price: float, voo_current_price: float) -> float:
        if voo_start_price <= 0:
            return self.budget
        return self.budget * (voo_current_price / voo_start_price)

    # --- sizing ----------------------------------------------------------- #
    def size_contracts(self, premium: float, planned_dollars: float) -> int:
        """Whole contracts affordable within the per-name cap and available cash."""
        if premium <= 0:
            return 0
        cap = min(settings.max_position_pct * self.budget, self.available_cash())
        budget_for_name = min(planned_dollars, cap)
        per_contract = premium * settings.option_multiplier
        return int(math.floor(budget_for_name / per_contract))

    # --- lifecycle -------------------------------------------------------- #
    def create_pending(
        self,
        *,
        ticker: str,
        strategy: str,
        contract: OptionContract,
        snapshot: dict[str, Any],
        planned_dollars: float,
        entry_premium_est: float,
        underlying_stop: float,
        underlying_target: float,
    ) -> OptionTrade | None:
        """Queue a PENDING long call; None when not even one contract fits the cap."""
        contracts = self.size_contracts(entry_premium_est, planned_dollars)
        if contracts < 1:
            return None
        cost = contracts * entry_premium_est * settings.option_multiplier
        trade = OptionTrade(
            ticker=ticker.upper(),
            strategy=strategy,
            status="PENDING",
            option_type=contract.option_type,
            strike=contract.strike,
            expiry=contract.expiry,
            dte_at_entry=contract.dte,
            contracts=contracts,
            multiplier=settings.option_multiplier,
            entry_iv=contract.iv,
            entry_delta=contract.delta,
            price_source=contract.source,
            cost_basis=cost,
            underlying_stop=underlying_stop,
            underlying_target=underlying_target,
            signal_snapshot_json=json.dumps({**snapshot, "contract": contract.to_summary()}),
        )
        return self.storage.add_option_trade(trade)

    def execute_pending(
        self, trade: OptionTrade, *, fill_premium: float, on: Date, underlying: float
    ) -> OptionTrade:
        """Fill a PENDING long call at ``fill_premium`` (already slippage-adjusted)."""
        trade.entry_premium = fill_premium
        trade.entry_date = on
        trade.underlying_entry = underlying
        trade.cost_basis = trade.contracts * fill_premium * trade.multiplier
        trade.tp_premium = fill_premium * (1.0 + settings.option_tp_pct / 100.0)
        trade.sl_premium = fill_premium * (1.0 - settings.option_sl_pct / 100.0)
        trade.status = "OPEN"
        return self.storage.update_option_trade(trade)

    def close_trade(
        self, trade: OptionTrade, *, exit_premium: float, exit_reason: str, on: Date,
        underlying: float, gap_note: str = "",
    ) -> OptionTrade:
        """Close an OPEN long call; P&L = (exit-entry) * contracts * multiplier."""
        trade.exit_premium = exit_premium
        trade.exit_date = on
        trade.exit_reason = exit_reason
        trade.pending_exit_reason = ""
        trade.underlying_exit = underlying
        trade.pnl_dollars = (exit_premium - trade.entry_premium) * trade.contracts * trade.multiplier
        cost = trade.entry_premium * trade.contracts * trade.multiplier
        trade.pnl_pct = (trade.pnl_dollars / cost * 100.0) if cost else 0.0
        if trade.entry_date is not None:
            trade.holding_days = (on - trade.entry_date).days
        trade.gap_note = gap_note
        trade.status = "CLOSED"
        return self.storage.update_option_trade(trade)
