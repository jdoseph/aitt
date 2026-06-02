"""Option queueing + fill + monitor jobs (Session 16)."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from src.agent import jobs
from src.core.options.option_trades import OptionBook
from src.core.storage import Storage


def _seed_candidate(store: Storage, ticker: str, *, on: date, score: float, rank: int, grade: str) -> None:
    store.upsert_daily_score(ticker=ticker, date=on, score=score, rank=rank, n=10)
    store.upsert_dossier(
        ticker=ticker, date=on, grade=grade, strongest_bull="x", strongest_bear="y",
        summary={"trade_plan": {"stop": 90.0, "target": 120.0, "entry": 100.0}},
    )


def _price_df(close: float, n: int = 60) -> pd.DataFrame:
    # A realistic, mildly-volatile walk (~20% annualized) so realized_vol > 0 and
    # the model picks a sane ~0.60-delta contract. A perfectly flat series would
    # give iv=0 and a degenerate deep-ITM strike, which never happens live.
    rng = np.random.default_rng(7)
    closes = [close]
    for r in rng.normal(0.0, 0.012, n - 1):
        closes.append(closes[-1] * (1.0 + r))
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame({"open": closes, "high": closes, "low": closes,
                         "close": closes, "volume": [1_000_000] * n}, index=idx)


def test_queue_option_entries_creates_pending() -> None:
    store = Storage.in_memory()
    on = date(2024, 3, 1)
    _seed_candidate(store, "NVDA", on=on, score=80, rank=1, grade="HIGH-QUALITY")
    store.upsert_prices("NVDA", _price_df(100.0))
    book = OptionBook(store, budget=5000.0)
    created = jobs.queue_option_entries(
        book, store, on=on, regime_label="RISK_ON",
        price_provider=lambda t: store.get_prices(t),
        chain_provider=lambda t, dte, as_of: None,  # force model path
    )
    assert [t.ticker for t in created] == ["NVDA"]
    pend = book.pending_trades()[0]
    assert pend.contracts >= 1
    assert pend.price_source == "model"


def test_queue_option_entries_suppressed_in_risk_off() -> None:
    store = Storage.in_memory()
    on = date(2024, 3, 1)
    _seed_candidate(store, "NVDA", on=on, score=90, rank=1, grade="HIGH-QUALITY")
    store.upsert_prices("NVDA", _price_df(100.0))
    book = OptionBook(store, budget=5000.0)
    created = jobs.queue_option_entries(
        book, store, on=on, regime_label="RISK_OFF",
        price_provider=lambda t: store.get_prices(t),
        chain_provider=lambda t, dte, as_of: None,
    )
    assert created == []


def test_execute_option_open_fills_pending() -> None:
    store = Storage.in_memory()
    on = date(2024, 3, 1)
    _seed_candidate(store, "NVDA", on=on, score=80, rank=1, grade="DECENT")
    store.upsert_prices("NVDA", _price_df(100.0))
    book = OptionBook(store, budget=5000.0)
    jobs.queue_option_entries(
        book, store, on=on, regime_label="RISK_ON",
        price_provider=lambda t: store.get_prices(t),
        chain_provider=lambda t, dte, as_of: None,
    )
    opened = jobs.execute_option_open(
        book, on=date(2024, 3, 4),
        underlying_provider=lambda t, d: 101.0,
        chain_provider=lambda t, dte, as_of: None,
    )
    assert len(opened) == 1
    assert opened[0].status == "OPEN"
    assert opened[0].entry_premium > 0.0


def test_monitor_option_positions_closes_on_target() -> None:
    store = Storage.in_memory()
    book = OptionBook(store, budget=5000.0)
    from src.core.options.contracts import OptionContract
    c = OptionContract(option_type="call", strike=95.0, expiry=date(2024, 4, 19),
                       dte=45, iv=0.30, delta=0.60, source="model")
    t = book.create_pending(ticker="NVDA", strategy="composite", contract=c, snapshot={},
                            planned_dollars=1500.0, entry_premium_est=7.0,
                            underlying_stop=90.0, underlying_target=120.0)
    book.execute_pending(t, fill_premium=7.0, on=date(2024, 3, 1), underlying=100.0)
    closed = jobs.monitor_option_positions(
        book, on=date(2024, 3, 15),
        underlying_provider=lambda t: 121.0,  # >= target
    )
    assert len(closed) == 1
    assert closed[0].exit_reason == "EXIT_TARGET"


def test_option_daily_summary_writes_cashbook() -> None:
    store = Storage.in_memory()
    book = OptionBook(store, budget=5000.0)
    from src.core.options.contracts import OptionContract
    c = OptionContract(option_type="call", strike=95.0, expiry=date(2024, 4, 19),
                       dte=45, iv=0.30, delta=0.60, source="model")
    t = book.create_pending(ticker="NVDA", strategy="composite", contract=c, snapshot={},
                            planned_dollars=1500.0, entry_premium_est=7.0,
                            underlying_stop=90.0, underlying_target=120.0)
    book.execute_pending(t, fill_premium=7.0, on=date(2024, 3, 1), underlying=100.0)
    jobs.option_daily_summary(
        store, on=date(2024, 3, 4),
        underlying_provider=lambda t: 102.0,
        voo_price=None,
    )
    cb = store.get_option_cashbook()
    assert len(cb) == 1
    assert cb[0].total_nav > 0.0
