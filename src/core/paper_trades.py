"""Paper-trade lifecycle + book accounting (Session 15).

:class:`PaperBook` wraps a :class:`~src.core.storage.Storage` and owns the trade
state machine — PENDING (queued at daily close) → OPEN (filled at next open) →
CLOSED (stop/target/daily exit) — plus budget accounting, conviction sizing, and
NAV. All fake money; nothing here ever touches a broker.

Cash accounting (derivable entirely from the trade rows):

* ``available_cash`` (spendable, conservative) = budget − cost of OPEN and
  PENDING positions + realized P&L of CLOSED trades. PENDING reservations are
  subtracted so a single night's queue can't over-commit the budget.
* NAV cash = budget − OPEN cost + realized P&L (PENDING is not yet spent, so it
  still counts as cash for NAV).
"""

from __future__ import annotations

import json
from datetime import date as Date
from typing import Any

from src.core.config import settings
from src.core.execution import BUY, SELL, apply_slippage
from src.core.storage import PaperTrade, Storage


class PaperBook:
    """The autonomous paper account: lifecycle + budget + sizing + NAV."""

    def __init__(self, storage: Storage, *, budget: float | None = None) -> None:
        self.storage = storage
        self.budget = budget if budget is not None else settings.paper_budget

    # --- queries ---------------------------------------------------------- #
    def pending_trades(self) -> list[PaperTrade]:
        return self.storage.get_paper_trades(status="PENDING")

    def open_trades(self) -> list[PaperTrade]:
        return self.storage.get_paper_trades(status="OPEN")

    def closed_trades(self) -> list[PaperTrade]:
        return self.storage.get_paper_trades(status="CLOSED")

    def has_active(self, ticker: str) -> bool:
        """True if the ticker already has an OPEN or PENDING paper trade."""
        ticker = ticker.upper()
        return any(
            t.ticker == ticker for t in (*self.pending_trades(), *self.open_trades())
        )

    # --- cash accounting -------------------------------------------------- #
    def _committed_cost(self, *, include_pending: bool) -> float:
        statuses = ("OPEN", "PENDING") if include_pending else ("OPEN",)
        total = 0.0
        for status in statuses:
            total += sum(t.cost_basis for t in self.storage.get_paper_trades(status=status))
        return total

    def _realized_pnl(self) -> float:
        return sum(t.pnl_dollars for t in self.closed_trades())

    def available_cash(self) -> float:
        """Spendable cash: budget − OPEN/PENDING cost + realized P&L (never < 0)."""
        cash = self.budget - self._committed_cost(include_pending=True) + self._realized_pnl()
        return max(0.0, cash)

    def _nav_cash(self) -> float:
        """Actual free cash (PENDING reservations are not yet spent)."""
        return self.budget - self._committed_cost(include_pending=False) + self._realized_pnl()

    def invested_value(self, prices: dict[str, float]) -> float:
        """Market value of OPEN positions at the supplied prices."""
        return sum(t.shares * prices.get(t.ticker, t.entry_price) for t in self.open_trades())

    def current_nav(self, prices: dict[str, float]) -> float:
        """Total paper NAV: free cash + market value of OPEN positions."""
        return self._nav_cash() + self.invested_value(prices)

    def voo_nav(self, voo_start_price: float, voo_current_price: float) -> float:
        """Same-dollar VOO benchmark: the budget invested in VOO at the start date."""
        if voo_start_price <= 0:
            return self.budget
        return self.budget * (voo_current_price / voo_start_price)

    def voo_start_price(self) -> float | None:
        """The VOO close recorded on the first cashbook day — the benchmark anchor."""
        for entry in self.storage.get_cashbook():  # oldest → newest
            if entry.voo_price > 0:
                return entry.voo_price
        return None

    def voo_nav_since_start(self, current_voo_price: float) -> float:
        """Same-dollar VOO benchmark from the first recorded day to now.

        Before any cashbook exists the anchor is ``current_voo_price`` itself, so
        the benchmark starts exactly at the budget (no day-zero drift).
        """
        start = self.voo_start_price()
        if start is None:
            start = current_voo_price
        return self.voo_nav(start, current_voo_price)

    # --- sizing ----------------------------------------------------------- #
    def size_position(self, composite_score: float) -> float:
        """Budget-constrained conviction size in dollars (0 when cash is too thin).

        base = score/100 · base_position_pct · available_cash, clamped to
        [min_position_size, min(max_position_pct·budget, available_cash·0.5)].
        """
        cash = self.available_cash()
        if cash < settings.min_position_size:
            return 0.0
        max_size = min(settings.max_position_pct * self.budget, cash * 0.5)
        if max_size < settings.min_position_size:
            return 0.0
        base = (composite_score / 100.0) * settings.base_position_pct * cash
        return float(min(max(base, settings.min_position_size), max_size))

    # --- lifecycle -------------------------------------------------------- #
    def create_pending(
        self,
        *,
        ticker: str,
        strategy: str,
        signal_id: int | None,
        snapshot: dict[str, Any],
        planned_dollars: float,
        stop_price: float,
        target_price: float,
    ) -> PaperTrade:
        """Queue a PENDING entry with the decision snapshot frozen in immutably."""
        trade = PaperTrade(
            ticker=ticker.upper(),
            strategy=strategy,
            entry_signal_id=signal_id,
            status="PENDING",
            cost_basis=planned_dollars,
            stop_price=stop_price,
            target_price=target_price,
            signal_snapshot_json=json.dumps(snapshot),
        )
        return self.storage.add_paper_trade(trade)

    def execute_pending(
        self,
        trade: PaperTrade,
        *,
        open_price: float,
        slippage_bps: float,
        on: Date,
    ) -> PaperTrade:
        """Fill a PENDING entry at the open + slippage (PENDING → OPEN)."""
        fill = apply_slippage(open_price, slippage_bps, BUY)
        trade.entry_price = fill
        trade.entry_slippage_bps = slippage_bps
        trade.entry_date = on
        trade.shares = trade.cost_basis / fill if fill > 0 else 0.0
        trade.status = "OPEN"
        return self.storage.update_paper_trade(trade)

    def close_trade(
        self,
        trade: PaperTrade,
        *,
        exit_price: float,
        exit_reason: str,
        slippage_bps: float,
        on: Date,
        gap_note: str = "",
    ) -> PaperTrade:
        """Close an OPEN position at the exit price + slippage (OPEN → CLOSED)."""
        fill = apply_slippage(exit_price, slippage_bps, SELL)
        proceeds = trade.shares * fill
        trade.exit_price = fill
        trade.exit_slippage_bps = slippage_bps
        trade.exit_date = on
        trade.exit_reason = exit_reason
        trade.pending_exit_reason = ""
        trade.pnl_dollars = proceeds - trade.cost_basis
        trade.pnl_pct = (trade.pnl_dollars / trade.cost_basis * 100.0) if trade.cost_basis else 0.0
        if trade.entry_date is not None:
            trade.holding_days = (on - trade.entry_date).days
        trade.gap_note = gap_note
        trade.status = "CLOSED"
        return self.storage.update_paper_trade(trade)
