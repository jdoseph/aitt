"""Storage-layer contract tests (Session 1)."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from src.core.storage import AlertRecord, SignalRecord, Storage


@pytest.fixture()
def store() -> Storage:
    return Storage.in_memory()


def _sample_prices(n: int = 5, start_close: float = 100.0) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=n, freq="D", name="date")
    closes = [start_close + i for i in range(n)]
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 1 for c in closes],
            "low": [c - 1 for c in closes],
            "close": closes,
            "volume": [1_000_000 + i for i in range(n)],
        },
        index=idx,
    )


# --- prices ---------------------------------------------------------------- #
def test_upsert_prices_returns_count_and_persists(store: Storage) -> None:
    df = _sample_prices(5)
    assert store.upsert_prices("nvda", df) == 5
    assert store.count_prices("NVDA") == 5  # case-insensitive store


def test_upsert_prices_is_idempotent(store: Storage) -> None:
    df = _sample_prices(5)
    store.upsert_prices("NVDA", df)
    store.upsert_prices("NVDA", df)  # same dates -> replace, not duplicate
    assert store.count_prices("NVDA") == 5


def test_upsert_prices_updates_existing_row(store: Storage) -> None:
    df = _sample_prices(3)
    store.upsert_prices("NVDA", df)
    df.loc[df.index[0], "close"] = 999.0
    store.upsert_prices("NVDA", df)
    stored = store.get_prices("NVDA")
    assert stored.iloc[0]["close"] == 999.0
    assert store.count_prices("NVDA") == 3


def test_get_prices_roundtrip_shape(store: Storage) -> None:
    store.upsert_prices("AMD", _sample_prices(4))
    out = store.get_prices("AMD")
    assert list(out.columns) == ["open", "high", "low", "close", "volume"]
    assert len(out) == 4
    assert out.index.is_monotonic_increasing


def test_get_prices_unknown_ticker_is_empty(store: Storage) -> None:
    out = store.get_prices("NOPE")
    assert out.empty


def test_count_prices_all_tickers(store: Storage) -> None:
    store.upsert_prices("NVDA", _sample_prices(5))
    store.upsert_prices("AMD", _sample_prices(3))
    assert store.count_prices() == 8


# --- signals --------------------------------------------------------------- #
def test_record_signal_upserts_by_ticker_date_strategy(store: Storage) -> None:
    d = date(2026, 1, 5)
    store.record_signal(
        ticker="VRT", date=d, strategy="ath_pullback", status="ENTRY_ZONE", confidence=1
    )
    # Same key, new status -> update in place.
    rec = store.record_signal(
        ticker="VRT",
        date=d,
        strategy="ath_pullback",
        status="MINOR_PULLBACK",
        confidence=2,
        patterns=["hammer"],
        details={"pullback_pct": 4.2},
    )
    sigs = store.get_signals(ticker="VRT", date=d)
    assert len(sigs) == 1
    assert sigs[0].status == "MINOR_PULLBACK"
    assert sigs[0].confidence == 2
    assert "hammer" in rec.patterns


def test_record_signal_different_strategies_coexist(store: Storage) -> None:
    d = date(2026, 1, 5)
    store.record_signal(ticker="VRT", date=d, strategy="ath_pullback", status="ENTRY_ZONE")
    store.record_signal(ticker="VRT", date=d, strategy="ema_pullback", status="AT_21_EMA")
    assert len(store.get_signals(ticker="VRT", date=d)) == 2


def test_get_signals_sorted_by_confidence_desc(store: Storage) -> None:
    d = date(2026, 1, 5)
    store.record_signal(ticker="A", date=d, strategy="s1", status="X", confidence=1)
    store.record_signal(ticker="B", date=d, strategy="s1", status="X", confidence=3)
    sigs = store.get_signals(date=d)
    assert [s.confidence for s in sigs] == [3, 1]


# --- alerts ---------------------------------------------------------------- #
def test_record_and_get_alerts(store: Storage) -> None:
    store.record_alert(
        ticker="VRT",
        date=date(2026, 1, 5),
        strategy="ath_pullback",
        status="ENTRY_ZONE",
        message="VRT in entry zone",
        confidence=3,
        patterns=["bullish_engulfing"],
    )
    alerts = store.get_alerts()
    assert len(alerts) == 1
    assert alerts[0].confidence == 3
    assert alerts[0].acknowledged is False


def test_acknowledge_alert(store: Storage) -> None:
    rec = store.record_alert(
        ticker="VRT", date=date(2026, 1, 5), strategy="ath_pullback", message="hi"
    )
    assert rec.id is not None
    assert store.acknowledge_alert(rec.id) is True
    assert store.get_alerts(acknowledged=False) == []
    assert len(store.get_alerts(acknowledged=True)) == 1


def test_acknowledge_missing_alert_returns_false(store: Storage) -> None:
    assert store.acknowledge_alert(9999) is False
