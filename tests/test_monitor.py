"""Intraday monitor + market-open fill tests (Session 15)."""

from __future__ import annotations

from datetime import date

import pytest

from src.agent import jobs
from src.core.paper_trades import PaperBook
from src.core.storage import Storage

NO_SLIP = lambda *a, **k: 0.0  # noqa: E731 - deterministic slippage for assertions


@pytest.fixture
def book(storage: Storage) -> PaperBook:
    return PaperBook(storage, budget=5000.0)


def _open_trade(book: PaperBook, *, stop: float, target: float, ticker: str = "NVDA"):
    t = book.create_pending(
        ticker=ticker,
        strategy="ema_pullback",
        signal_id=None,
        snapshot={},
        planned_dollars=1000.0,
        stop_price=stop,
        target_price=target,
    )
    return book.execute_pending(t, open_price=100.0, slippage_bps=0.0, on=date(2024, 1, 3))


def test_monitor_closes_on_stop_hit(book: PaperBook) -> None:
    _open_trade(book, stop=90.0, target=130.0)
    closed = jobs.monitor_positions(
        book, price_provider=lambda t: 89.0, on=date(2024, 1, 4), slippage_fn=NO_SLIP
    )
    assert len(closed) == 1
    assert closed[0].exit_reason == "EXIT_STOP"
    # closes at the stop level, not the (lower) current price
    assert closed[0].exit_price == pytest.approx(90.0)
    assert book.open_trades() == []


def test_monitor_closes_on_target_hit(book: PaperBook) -> None:
    _open_trade(book, stop=90.0, target=130.0)
    closed = jobs.monitor_positions(
        book, price_provider=lambda t: 131.0, on=date(2024, 1, 4), slippage_fn=NO_SLIP
    )
    assert len(closed) == 1
    assert closed[0].exit_reason == "EXIT_TARGET"
    assert closed[0].exit_price == pytest.approx(130.0)


def test_monitor_holds_between_stop_and_target(book: PaperBook) -> None:
    _open_trade(book, stop=90.0, target=130.0)
    closed = jobs.monitor_positions(
        book, price_provider=lambda t: 110.0, on=date(2024, 1, 4), slippage_fn=NO_SLIP
    )
    assert closed == []
    assert len(book.open_trades()) == 1


def test_monitor_stop_takes_priority_over_target() -> None:
    # A degenerate bar that is both <= stop and >= target resolves as a stop.
    s = Storage.in_memory()
    book = PaperBook(s, budget=5000.0)
    _open_trade(book, stop=120.0, target=120.0)
    closed = jobs.monitor_positions(
        book, price_provider=lambda t: 120.0, on=date(2024, 1, 4), slippage_fn=NO_SLIP
    )
    assert closed[0].exit_reason == "EXIT_STOP"


def test_execute_pending_fills_entries_at_open(book: PaperBook) -> None:
    book.create_pending(
        ticker="VRT",
        strategy="ema_pullback",
        signal_id=None,
        snapshot={},
        planned_dollars=800.0,
        stop_price=70.0,
        target_price=110.0,
    )
    opened, closed = jobs.execute_market_open(
        book,
        on=date(2024, 1, 3),
        open_price_provider=lambda t, d: 80.0,
        slippage_fn=NO_SLIP,
    )
    assert len(opened) == 1
    assert opened[0].status == "OPEN"
    assert opened[0].entry_price == pytest.approx(80.0)
    assert closed == []


def test_execute_market_open_gap_protects_stop(book: PaperBook) -> None:
    # Stop at 90 but the session gaps to a 85 open => closes at 85, gap documented.
    _open_trade(book, stop=90.0, target=130.0)
    opened, closed = jobs.execute_market_open(
        book,
        on=date(2024, 1, 4),
        open_price_provider=lambda t, d: 85.0,
        slippage_fn=NO_SLIP,
    )
    assert len(closed) == 1
    assert closed[0].exit_reason == "EXIT_STOP"
    assert closed[0].exit_price == pytest.approx(85.0)
    assert "gap" in closed[0].gap_note.lower()


def test_execute_market_open_processes_queued_daily_exit(book: PaperBook) -> None:
    t = _open_trade(book, stop=10.0, target=999.0)  # far levels so no stop/target
    t.pending_exit_reason = "EXIT_EMA"
    book.storage.update_paper_trade(t)
    opened, closed = jobs.execute_market_open(
        book,
        on=date(2024, 1, 4),
        open_price_provider=lambda t, d: 95.0,
        slippage_fn=NO_SLIP,
    )
    assert len(closed) == 1
    assert closed[0].exit_reason == "EXIT_EMA"
    assert closed[0].exit_price == pytest.approx(95.0)
