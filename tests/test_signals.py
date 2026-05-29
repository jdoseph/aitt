"""Signal orchestrator integration tests (Session 4)."""

from __future__ import annotations

import pandas as pd
import pytest

from src.agent import notify
from src.core.signals import Alert, SignalEngine
from src.core.storage import Storage
from tests.factories import make_ohlcv


@pytest.fixture()
def store() -> Storage:
    return Storage.in_memory()


# --- synthetic frames ------------------------------------------------------ #
def _ema_at21_frame() -> pd.DataFrame:
    # 65 flat bars pin the EMAs at 100; final bar dips through intrabar.
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


def _fresh_entry_zone_frame() -> pd.DataFrame:
    closes = [90.0] * 60
    highs = [90.45] * 60
    lows = [89.55] * 60
    highs[56], closes[56], lows[56] = 100.0, 99.0, 98.0  # ATH 3 bars from end (fresh)
    closes[59], highs[59], lows[59] = 93.0, 93.45, 92.5  # ~7% below ATH
    return make_ohlcv(closes, highs=highs, lows=lows)


def _stale_entry_zone_frame() -> pd.DataFrame:
    closes = [99.0 - (6.0 * i / 59) for i in range(60)]  # 99 -> 93
    highs = [c * 1.005 for c in closes]
    lows = [c * 0.995 for c in closes]
    highs[0] = 100.0  # ATH 59 bars ago (stale)
    return make_ohlcv(closes, highs=highs, lows=lows)


# --- tests ----------------------------------------------------------------- #
def test_cycle_populates_all_four_strategy_types(store: Storage) -> None:
    price_map = {
        "EMAT": _ema_at21_frame(),
        "BRKT": _breakout_frame(),
        "IPOX": _ipo_breakout_frame(),
    }
    SignalEngine(store).run_cycle(price_map)
    strategies = {r.strategy for r in store.get_signals()}
    assert {
        "ema_pullback",
        "ath_pullback",
        "consolidation_breakout",
        "ipo_base",
    } <= strategies


def test_ipo_no_signal_not_stored_for_seasoned(store: Storage) -> None:
    SignalEngine(store).run_cycle({"EMAT": _ema_at21_frame()})  # 65 bars
    ipo_rows = [r for r in store.get_signals() if r.strategy == "ipo_base"]
    assert ipo_rows == []


def test_ema_touch_alert_fires_then_dedupes(store: Storage) -> None:
    engine = SignalEngine(store)
    pm = {"EMAT": _ema_at21_frame()}

    first = engine.run_cycle(pm)
    ema_alerts = [a for a in first.alerts if a.strategy == "ema_pullback"]
    assert len(ema_alerts) == 1
    assert ema_alerts[0].status == "AT_21_EMA"

    # Re-running with identical data -> no new alert (status unchanged), and the
    # signal row is upserted, not duplicated.
    n_signals_before = len(store.get_signals())
    second = engine.run_cycle(pm)
    assert all(a.strategy != "ema_pullback" for a in second.alerts)
    assert len(store.get_signals()) == n_signals_before


def test_consolidation_breakout_alert(store: Storage) -> None:
    result = SignalEngine(store).run_cycle({"BRKT": _breakout_frame()})
    brk = [a for a in result.alerts if a.strategy == "consolidation_breakout"]
    assert len(brk) == 1 and brk[0].status == "BREAKOUT"


def test_ipo_breakout_alert(store: Storage) -> None:
    result = SignalEngine(store).run_cycle({"IPOX": _ipo_breakout_frame()})
    ipo = [a for a in result.alerts if a.strategy == "ipo_base"]
    assert len(ipo) == 1 and ipo[0].status == "IPO_BREAKOUT"


def test_ath_freshness_gate(store: Storage) -> None:
    result = SignalEngine(store).run_cycle(
        {"FRSH": _fresh_entry_zone_frame(), "STAL": _stale_entry_zone_frame()}
    )
    ath_alerts = {(a.ticker, a.status) for a in result.alerts if a.strategy == "ath_pullback"}
    assert ("FRSH", "ENTRY_ZONE") in ath_alerts
    assert not any(t == "STAL" for t, _ in ath_alerts)  # stale high suppressed


def test_alerts_sorted_by_confidence_desc(store: Storage) -> None:
    result = SignalEngine(store).run_cycle(
        {"EMAT": _ema_at21_frame(), "BRKT": _breakout_frame(), "FRSH": _fresh_entry_zone_frame()}
    )
    confidences = [a.confidence for a in result.alerts]
    assert confidences == sorted(confidences, reverse=True)


def test_alerts_persisted_to_db(store: Storage) -> None:
    SignalEngine(store).run_cycle({"EMAT": _ema_at21_frame()})
    assert len(store.get_alerts()) >= 1


def test_dispatch_routes_to_notifiers() -> None:
    sent: list[Alert] = []

    class Recorder(notify.Notifier):
        def send(self, alert: Alert) -> None:
            sent.append(alert)

    alert = Alert("X", "ema_pullback", "AT_21_EMA", "entry", "msg", 2, [], None)  # type: ignore[arg-type]
    n = notify.dispatch([alert], [Recorder()])
    assert n == 1 and sent == [alert]
