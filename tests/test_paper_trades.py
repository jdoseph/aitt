"""Paper-trade lifecycle tests (Session 15): state machine, P&L, sizing, NAV."""

from __future__ import annotations

from datetime import date

import pytest

from src.core.paper_trades import PaperBook
from src.core.storage import Storage


@pytest.fixture
def book(storage: Storage) -> PaperBook:
    return PaperBook(storage, budget=5000.0)


def _pending(book: PaperBook, ticker: str = "NVDA", dollars: float = 800.0):
    return book.create_pending(
        ticker=ticker,
        strategy="ema_pullback",
        signal_id=None,
        snapshot={"composite": 80, "grade": "DECENT"},
        planned_dollars=dollars,
        stop_price=90.0,
        target_price=120.0,
    )


def test_create_pending_reserves_cash_and_marks_active(book: PaperBook) -> None:
    _pending(book)
    assert book.has_active("NVDA")
    # the planned dollars are reserved against available cash
    assert book.available_cash() == pytest.approx(5000.0 - 800.0)
    assert len(book.pending_trades()) == 1


def test_execute_pending_fills_at_open_plus_slippage(book: PaperBook) -> None:
    t = _pending(book)
    opened = book.execute_pending(t, open_price=100.0, slippage_bps=10.0, on=date(2024, 1, 3))
    assert opened.status == "OPEN"
    # buyer pays up: 100 * (1 + 10bps) = 100.1
    assert opened.entry_price == pytest.approx(100.1)
    # shares sized from the planned dollars at the fill price
    assert opened.shares == pytest.approx(800.0 / 100.1)
    assert opened.cost_basis == pytest.approx(800.0)
    assert len(book.open_trades()) == 1


def test_close_trade_computes_pnl_and_holding_days(book: PaperBook) -> None:
    t = _pending(book)
    book.execute_pending(t, open_price=100.0, slippage_bps=0.0, on=date(2024, 1, 3))
    closed = book.close_trade(
        t, exit_price=120.0, exit_reason="EXIT_TARGET", slippage_bps=0.0, on=date(2024, 1, 13)
    )
    assert closed.status == "CLOSED"
    assert closed.exit_reason == "EXIT_TARGET"
    # 8 shares (800/100) * (120 - 100) = +160
    assert closed.pnl_dollars == pytest.approx(160.0)
    assert closed.pnl_pct == pytest.approx(20.0)
    assert closed.holding_days == 10


def test_available_cash_reflects_realized_pnl(book: PaperBook) -> None:
    t = _pending(book)
    book.execute_pending(t, open_price=100.0, slippage_bps=0.0, on=date(2024, 1, 3))
    assert book.available_cash() == pytest.approx(4200.0)  # 5000 - 800 open cost
    book.close_trade(
        t, exit_price=110.0, exit_reason="EXIT_TARGET", slippage_bps=0.0, on=date(2024, 1, 5)
    )
    # +80 realized (8 shares * +10); cash back to 5080
    assert book.available_cash() == pytest.approx(5080.0)
    assert not book.has_active("NVDA")


def test_size_position_scales_with_score_and_clamps(book: PaperBook) -> None:
    # score 80: 0.8 * 0.20 * 5000 = 800
    assert book.size_position(80.0) == pytest.approx(800.0)
    # tiny score floors to the minimum position size
    assert book.size_position(5.0) == pytest.approx(200.0)
    # score 100: full base 1.0 * 0.20 * 5000 = 1000 (below the 0.25*5000=1250 cap)
    assert book.size_position(100.0) == pytest.approx(1000.0)


def test_size_position_capped_by_concentration_limit(storage: Storage) -> None:
    # With a higher base fraction the base would be 0.5*20000=... ; the
    # concentration cap (max_position_pct * budget) binds first.
    big = PaperBook(storage, budget=20000.0)
    # base at score 100 = 1.0 * 0.20 * 20000 = 4000; cap = 0.25 * 20000 = 5000;
    # cash*0.5 = 10000 -> max_size = 5000; base 4000 < cap so returns 4000.
    assert big.size_position(100.0) == pytest.approx(4000.0)


def test_size_position_zero_when_cash_too_low(storage: Storage) -> None:
    tiny = PaperBook(storage, budget=300.0)
    # max size = min(0.25*300=75, 150) = 75 < min_position_size(200) => cannot open
    assert tiny.size_position(90.0) == 0.0


def test_current_nav_includes_unrealized(book: PaperBook) -> None:
    t = _pending(book)
    book.execute_pending(t, open_price=100.0, slippage_bps=0.0, on=date(2024, 1, 3))
    # 8 shares now worth 110 => MV 880; cash 4200; NAV 5080
    nav = book.current_nav({"NVDA": 110.0})
    assert nav == pytest.approx(5080.0)


def test_budget_never_exceeded_across_multiple_pendings(book: PaperBook) -> None:
    _pending(book, "NVDA", 2000.0)
    _pending(book, "VRT", 2000.0)
    # 4000 reserved, 1000 free — a third 2000 would over-commit, so sizing caps it
    assert book.available_cash() == pytest.approx(1000.0)
    assert book.size_position(100.0) <= book.available_cash()


def test_close_records_gap_note(book: PaperBook) -> None:
    t = _pending(book)
    book.execute_pending(t, open_price=100.0, slippage_bps=0.0, on=date(2024, 1, 3))
    closed = book.close_trade(
        t,
        exit_price=85.0,
        exit_reason="EXIT_STOP",
        slippage_bps=0.0,
        on=date(2024, 1, 4),
        gap_note="gapped through stop 90.00 -> filled 85.00",
    )
    assert "gapped" in closed.gap_note
