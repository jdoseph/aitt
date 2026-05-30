"""Session 6 hardening: resilience, edge cases, and pipeline integration.

These lock in the agent's "one bad ticker never aborts the cycle" guarantee, the
``--validate`` watchlist check, hot-reload, and a full fetch -> store -> evaluate
-> alert pipeline driven entirely by synthetic data (no network).
"""

from __future__ import annotations

import os
from typing import Any

import pandas as pd
import pytest

from src.agent import jobs
from src.core.data import DataFetchError
from src.core.signals import SignalEngine
from src.core.storage import Storage
from src.core.strategies.base import Strategy
from src.core.strategies.ema_pullback import EMAPullbackStrategy
from src.core.watchlist import WatchlistCache
from tests.factories import make_ohlcv


@pytest.fixture()
def store() -> Storage:
    return Storage.in_memory()


# --- synthetic frames ------------------------------------------------------ #
def _ema_at21_frame() -> pd.DataFrame:
    closes = [100.0] * 64 + [100.5]
    highs = [100.5] * 64 + [101.0]
    lows = [99.5] * 64 + [99.5]
    return make_ohlcv(closes, highs=highs, lows=lows)


def _breakout_frame() -> pd.DataFrame:
    closes = [100.0] * 60 + [105.0]
    vols = [1_000_000.0] * 60 + [3_000_000.0]
    return make_ohlcv(closes, volumes=vols)


def _ipo_breakout_frame() -> pd.DataFrame:
    highs = [100.0] * 5 + [96.0] * 14 + [101.1]
    closes = [99.0] * 5 + [95.0] * 14 + [101.0]
    vols = [1_000_000.0] * 19 + [3_000_000.0]
    return make_ohlcv(closes, highs=highs, volumes=vols)


# --- per-ticker resilience ------------------------------------------------- #
class _BoomStrategy(Strategy):
    """A strategy that always raises — stands in for a malformed-data crash."""

    name = "boom"

    def classify(self, df: pd.DataFrame) -> tuple[str, dict[str, Any]]:
        raise RuntimeError("boom")


def test_failing_strategy_does_not_abort_cycle(store: Storage) -> None:
    engine = SignalEngine(store, strategies=(_BoomStrategy, EMAPullbackStrategy))
    result = engine.run_cycle({"EMAT": _ema_at21_frame()})

    # The boom strategy's exception is swallowed; the healthy strategy still ran.
    assert any(a.strategy == "ema_pullback" for a in result.alerts)
    assert all(r.strategy != "boom" for r in store.get_signals())


def test_one_bad_ticker_does_not_block_the_others(store: Storage) -> None:
    # An empty frame for one ticker must not stop the others from evaluating.
    result = SignalEngine(store).run_cycle(
        {"BAD": pd.DataFrame(), "BRKT": _breakout_frame()}
    )
    assert any(a.ticker == "BRKT" for a in result.alerts)


def test_thin_data_does_not_crash(store: Storage) -> None:
    # Far fewer bars than any strategy needs — should classify as insufficient,
    # never raise, and never produce an alert.
    result = SignalEngine(store).run_cycle({"TINY": make_ohlcv([100.0, 101.0, 102.0])})
    assert result.n_tickers == 1
    assert result.alerts == []


def test_fake_ipo_ticker_activates_ipo_strategy(store: Storage) -> None:
    # Spec verify item: a fresh (<60 bar) name breaking its IPO high fires Strategy 4,
    # even when it isn't a watchlist member (layer/capex degrade gracefully).
    result = SignalEngine(store).run_cycle({"ANTH": _ipo_breakout_frame()})
    assert any(
        a.strategy == "ipo_base" and a.status == "IPO_BREAKOUT" for a in result.alerts
    )


# --- watchlist validation (--validate) ------------------------------------- #
def _ok_frame(_ticker: str, _bars: int) -> pd.DataFrame:
    return make_ohlcv([1.0, 2.0, 3.0, 4.0, 5.0])


def test_validate_watchlist_all_ok() -> None:
    report = jobs.validate_watchlist(fetcher=_ok_frame)
    assert report.all_ok
    assert not report.failed
    assert "all OK" in report.summary()


def test_validate_watchlist_reports_unfetchable() -> None:
    def fetch(ticker: str, bars: int) -> pd.DataFrame:
        if ticker == "NVDA":
            raise DataFetchError("NVDA: delisted")
        return _ok_frame(ticker, bars)

    report = jobs.validate_watchlist(fetcher=fetch)
    assert not report.all_ok
    assert "NVDA" in report.failed
    assert "NVDA" in report.summary() and "UNFETCHABLE" in report.summary()


def test_validate_watchlist_flags_empty_frame() -> None:
    report = jobs.validate_watchlist(fetcher=lambda _t, _b: pd.DataFrame())
    assert not report.all_ok
    assert all(reason == "no data" for reason in report.failed.values())


# --- hot reload ------------------------------------------------------------ #
_WL_ONE = """\
layers:
  layer1: "Layer One"
tickers:
  - ticker: AAA
    name: Alpha
    layer: layer1
"""
_WL_TWO = _WL_ONE + """\
  - ticker: BBB
    name: Bravo
    layer: layer1
"""


def test_watchlist_cache_hot_reloads_new_ticker(tmp_path: Any) -> None:
    path = tmp_path / "wl.yaml"
    path.write_text(_WL_ONE, encoding="utf-8")
    cache = WatchlistCache(path)
    assert cache.get().tickers == ["AAA"]

    # Add a ticker mid-session; bump mtime so the change is detectable even on
    # filesystems with coarse timestamp resolution.
    path.write_text(_WL_TWO, encoding="utf-8")
    stamp = path.stat().st_mtime + 10
    os.utime(path, (stamp, stamp))
    assert cache.get().tickers == ["AAA", "BBB"]


# --- full pipeline (fetch -> store -> evaluate -> alert) -------------------- #
def test_run_once_pipeline_persists_signals_and_alerts(
    store: Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    frames = {"NVDA": _breakout_frame()}
    monkeypatch.setattr(jobs, "fetch_many", lambda tickers, *a, **k: frames)
    # Keep the cycle offline + deterministic: no benchmark/earnings/news/backtest.
    monkeypatch.setattr(jobs.settings, "enable_scorecard", False)
    monkeypatch.setattr(jobs.settings, "enable_backtest", False)
    dispatched: list[list[Any]] = []
    monkeypatch.setattr(
        jobs.notify, "dispatch", lambda alerts: (dispatched.append(alerts), len(alerts))[1]
    )

    result = jobs.run_once(store, fetch=True)

    assert result.n_tickers == 1
    assert any(a.strategy == "consolidation_breakout" for a in result.alerts)
    assert not store.get_prices("NVDA").empty  # prices were fetched + persisted
    assert len(store.get_alerts()) >= 1  # alert reached the DB
    assert dispatched and dispatched[0] == result.alerts  # ...and the notifier
