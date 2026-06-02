"""OptionBook lifecycle + accounting (Session 16)."""

from __future__ import annotations

from datetime import date

import pytest

from src.core.options.contracts import OptionContract
from src.core.options.option_trades import OptionBook
from src.core.storage import Storage


# Budget 6000 -> per-name concentration cap (25%) is 1500, so a 2-contract
# position at $7 ($1400) fits within the cap; this exercises the floor-to-whole-
# contracts sizing without tripping the cap (which test_..._exceeds_cap covers).
@pytest.fixture
def book(storage: Storage) -> OptionBook:
    return OptionBook(storage, budget=6000.0)


def _contract() -> OptionContract:
    return OptionContract(
        option_type="call", strike=95.0, expiry=date(2024, 4, 19),
        dte=45, iv=0.33, delta=0.60, source="model",
    )


def _pending(book: OptionBook, ticker: str = "NVDA", premium: float = 7.0, planned: float = 1500.0):
    return book.create_pending(
        ticker=ticker, strategy="composite", contract=_contract(),
        snapshot={"composite": 80}, planned_dollars=planned,
        entry_premium_est=premium, underlying_stop=90.0, underlying_target=120.0,
    )


def test_create_pending_sizes_contracts_and_reserves_cash(book: OptionBook) -> None:
    t = _pending(book, premium=7.0, planned=1500.0)
    # 1500 / (7 * 100) = 2.14 -> floor 2 contracts; cost = 2*7*100 = 1400.
    assert t.contracts == 2
    assert t.cost_basis == pytest.approx(1400.0)
    assert book.available_cash() == pytest.approx(6000.0 - 1400.0)


def test_create_pending_skips_when_one_contract_exceeds_cap(storage: Storage) -> None:
    book = OptionBook(storage, budget=5000.0)  # cap = 0.25 * 5000 = 1250
    # premium 15 -> one contract costs 1500 > cap -> 0 contracts -> None.
    t = book.create_pending(
        ticker="NVDA", strategy="composite", contract=_contract(),
        snapshot={}, planned_dollars=2000.0, entry_premium_est=15.0,
        underlying_stop=90.0, underlying_target=120.0,
    )
    assert t is None
    assert book.pending_trades() == []


def test_execute_pending_fills_and_sets_premium_guards(book: OptionBook) -> None:
    t = _pending(book, premium=7.0)
    opened = book.execute_pending(t, fill_premium=7.40, on=date(2024, 3, 1), underlying=100.0)
    assert opened.status == "OPEN"
    assert opened.entry_premium == pytest.approx(7.40)
    assert opened.cost_basis == pytest.approx(2 * 7.40 * 100)
    assert opened.tp_premium == pytest.approx(7.40 * 1.5)   # +50%
    assert opened.sl_premium == pytest.approx(7.40 * 0.5)   # -50%


def test_close_trade_pnl_uses_multiplier(book: OptionBook) -> None:
    t = _pending(book, premium=7.0)
    book.execute_pending(t, fill_premium=7.0, on=date(2024, 3, 1), underlying=100.0)
    closed = book.close_trade(
        t, exit_premium=10.0, exit_reason="EXIT_TARGET", on=date(2024, 3, 20), underlying=115.0
    )
    assert closed.status == "CLOSED"
    # (10 - 7) * 2 contracts * 100 = 600
    assert closed.pnl_dollars == pytest.approx(600.0)
    assert closed.holding_days == 19


def test_current_nav_marks_open_positions(book: OptionBook) -> None:
    t = _pending(book, premium=7.0)
    book.execute_pending(t, fill_premium=7.0, on=date(2024, 3, 1), underlying=100.0)
    # mark each open contract at premium 9 -> MV = 2*9*100 = 1800; cash = 6000-1400=4600.
    nav = book.current_nav({t.trade_id: 9.0})
    assert nav == pytest.approx(4600.0 + 1800.0)
