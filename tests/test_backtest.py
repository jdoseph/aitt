"""Historical backtest replay tests (Session 8)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.core import backtest
from src.core.storage import Storage
from tests.factories import make_ohlcv


class _DummyStrategy:
    """Classifies the latest bar as SIG when close >= 12, else FLAT."""

    name = "dummy"
    min_bars = 1

    def classify(self, df: pd.DataFrame) -> tuple[str, dict[str, Any]]:
        return ("SIG" if float(df["close"].iloc[-1]) >= 12 else "FLAT"), {}


def test_replay_counts_transitions_and_forward_returns() -> None:
    # SIG (close>=12) at idx 2,5,6,7; transitions INTO SIG at idx 2 and idx 5.
    closes = [10, 8, 12, 9, 7, 12, 18, 20]
    df = make_ohlcv(closes)
    stats = backtest.replay(df, _DummyStrategy(), "SIG", horizons=[2])
    s = stats[2]
    # idx2 -> close[4]=7 (loss); idx5 -> close[7]=20 (win)
    assert s.n == 2
    assert s.wins == 1
    assert s.win_rate == 50.0


def test_replay_excludes_occurrences_without_full_horizon() -> None:
    closes = [10, 8, 12, 14]  # transition into SIG at idx 2; horizon 5 has no data
    df = make_ohlcv(closes)
    stats = backtest.replay(df, _DummyStrategy(), "SIG", horizons=[5])
    assert stats[5].n == 0


def test_compute_stats_caches_and_reuses(monkeypatch: Any) -> None:
    store = Storage.in_memory()
    monkeypatch.setitem(backtest.STRATEGY_BY_NAME, "dummy", _DummyStrategy)

    calls = {"n": 0}

    def fetcher(_ticker: str) -> pd.DataFrame:
        calls["n"] += 1
        return make_ohlcv([10, 8, 12, 9, 7, 12, 18, 20])

    first = backtest.compute_stats("TST", "dummy", "SIG", store=store, fetcher=fetcher, horizons=[2])
    assert first is not None and first.primary(2) is not None
    assert first.primary(2).n == 2
    # Second call is served from the fresh cache -> fetcher not called again.
    second = backtest.compute_stats("TST", "dummy", "SIG", store=store, fetcher=fetcher, horizons=[2])
    assert second is not None
    assert calls["n"] == 1


def test_compute_stats_unknown_strategy_returns_none() -> None:
    store = Storage.in_memory()
    out = backtest.compute_stats(
        "TST", "no_such_strategy", "SIG", store=store, fetcher=lambda _t: make_ohlcv([1, 2, 3])
    )
    assert out is None
