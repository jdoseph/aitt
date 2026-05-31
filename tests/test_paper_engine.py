"""Entry/exit queueing + daily-eval wiring tests (Session 15)."""

from __future__ import annotations

import json
from datetime import date

import pytest

from src.agent import jobs, notify
from src.core.paper_trades import PaperBook
from src.core.storage import Storage


def _seed_candidate(
    store: Storage, ticker: str, *, on: date, score: float, rank: int, grade: str,
    stop: float = 90.0, target: float = 130.0,
) -> None:
    store.upsert_daily_score(ticker=ticker, date=on, score=score, rank=rank, n=10)
    store.upsert_dossier(
        ticker=ticker,
        date=on,
        grade=grade,
        strongest_bull="x",
        strongest_bear="y",
        summary={"trade_plan": {"stop": stop, "target": target, "entry": 100.0}},
    )


def test_queue_entries_opens_pending_for_qualifying_names() -> None:
    store = Storage.in_memory()
    book = PaperBook(store, budget=5000.0)
    on = date(2024, 1, 2)
    _seed_candidate(store, "NVDA", on=on, score=80, rank=1, grade="HIGH-QUALITY")
    created = jobs.queue_entries(book, store, on=on, regime_label="RISK_ON")
    assert [t.ticker for t in created] == ["NVDA"]
    pend = book.pending_trades()[0]
    assert pend.stop_price == 90.0 and pend.target_price == 130.0
    # the decision snapshot is frozen in
    assert json.loads(pend.signal_snapshot_json)["composite"] == 80


def test_queue_entries_skips_low_score_and_grade() -> None:
    store = Storage.in_memory()
    book = PaperBook(store, budget=5000.0)
    on = date(2024, 1, 2)
    _seed_candidate(store, "LOWS", on=on, score=40, rank=1, grade="HIGH-QUALITY")  # score < 55
    _seed_candidate(store, "LOWG", on=on, score=80, rank=2, grade="MARGINAL")  # grade < DECENT
    created = jobs.queue_entries(book, store, on=on, regime_label="RISK_ON")
    assert created == []


def test_queue_entries_suppressed_in_risk_off() -> None:
    store = Storage.in_memory()
    book = PaperBook(store, budget=5000.0)
    on = date(2024, 1, 2)
    _seed_candidate(store, "NVDA", on=on, score=90, rank=1, grade="HIGH-QUALITY")
    assert jobs.queue_entries(book, store, on=on, regime_label="RISK_OFF") == []


def test_queue_entries_skips_already_active() -> None:
    store = Storage.in_memory()
    book = PaperBook(store, budget=5000.0)
    on = date(2024, 1, 2)
    _seed_candidate(store, "NVDA", on=on, score=80, rank=1, grade="DECENT")
    book.create_pending(
        ticker="NVDA", strategy="x", signal_id=None, snapshot={},
        planned_dollars=500.0, stop_price=1.0, target_price=2.0,
    )
    assert jobs.queue_entries(book, store, on=on, regime_label="RISK_ON") == []


def test_queue_daily_exits_flags_rotation() -> None:
    store = Storage.in_memory()
    book = PaperBook(store, budget=5000.0)
    on = date(2024, 1, 10)
    t = book.create_pending(
        ticker="NVDA", strategy="x", signal_id=None, snapshot={},
        planned_dollars=1000.0, stop_price=1.0, target_price=9999.0,
    )
    book.execute_pending(t, open_price=100.0, slippage_bps=0.0, on=date(2024, 1, 3))
    # rank 20 is past the default paper_exit_rank (12) => rotation exit queued
    store.upsert_daily_score(ticker="NVDA", date=on, score=50, rank=20, n=30)
    flagged = jobs.queue_daily_exits(book, store, on=on, regime_label="RISK_ON")
    assert len(flagged) == 1
    assert flagged[0].pending_exit_reason == "EXIT_ROTATION"


def test_queue_daily_exits_flags_regime_off() -> None:
    store = Storage.in_memory()
    book = PaperBook(store, budget=5000.0)
    on = date(2024, 1, 10)
    t = book.create_pending(
        ticker="NVDA", strategy="x", signal_id=None, snapshot={},
        planned_dollars=1000.0, stop_price=1.0, target_price=9999.0,
    )
    book.execute_pending(t, open_price=100.0, slippage_bps=0.0, on=date(2024, 1, 3))
    store.upsert_daily_score(ticker="NVDA", date=on, score=80, rank=1, n=30)
    flagged = jobs.queue_daily_exits(book, store, on=on, regime_label="RISK_OFF")
    assert flagged[0].pending_exit_reason == "EXIT_REGIME"


# --- notification formatting ------------------------------------------------ #
def test_format_trade_opened_and_closed() -> None:
    store = Storage.in_memory()
    book = PaperBook(store, budget=5000.0)
    t = book.create_pending(
        ticker="NVDA", strategy="x", signal_id=None, snapshot={},
        planned_dollars=800.0, stop_price=90.0, target_price=120.0,
    )
    book.execute_pending(t, open_price=100.0, slippage_bps=0.0, on=date(2024, 1, 3))
    assert "OPENED NVDA" in notify.format_trade_opened(t)
    closed = book.close_trade(
        t, exit_price=120.0, exit_reason="EXIT_TARGET", slippage_bps=0.0, on=date(2024, 1, 13)
    )
    line = notify.format_trade_closed(closed)
    assert "TARGET HIT" in line and "+" in line


def test_format_daily_summary_shows_alpha_vs_budget() -> None:
    line = notify.format_daily_summary(
        nav=5300.0, budget=5000.0, open_count=3, closed_today=1, realized_today=120.0
    )
    assert "+$300" in line and "3 open" in line


def test_is_trading_day_excludes_weekends_and_holidays() -> None:
    assert jobs.is_trading_day(date(2024, 1, 6)) is False  # Saturday
    assert jobs.is_trading_day(date(2024, 1, 1)) is False  # New Year's Day (holiday)
    assert jobs.is_trading_day(date(2024, 1, 3)) is True  # ordinary Wednesday
