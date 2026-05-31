"""Paper-engine storage tables (Session 15): paper_trades + cashbook CRUD."""

from __future__ import annotations

from datetime import date

from src.core.storage import PaperTrade, Storage


def test_paper_trade_roundtrip_and_status_filter(storage: Storage) -> None:
    pending = storage.add_paper_trade(
        PaperTrade(
            ticker="nvda",
            strategy="ema_pullback",
            status="PENDING",
            cost_basis=1000.0,
            stop_price=90.0,
            target_price=120.0,
            signal_snapshot_json='{"composite": 80}',
        )
    )
    assert pending.trade_id is not None
    assert pending.ticker == "NVDA"  # normalized on insert

    assert len(storage.get_paper_trades(status="PENDING")) == 1
    assert storage.get_paper_trades(status="OPEN") == []

    pending.status = "OPEN"
    pending.shares = 10.0
    pending.entry_price = 100.0
    storage.update_paper_trade(pending)

    reloaded = storage.get_paper_trade(pending.trade_id)
    assert reloaded is not None
    assert reloaded.status == "OPEN"
    assert reloaded.shares == 10.0
    assert len(storage.get_paper_trades(status="OPEN")) == 1


def test_cashbook_upsert_is_idempotent_on_date(storage: Storage) -> None:
    storage.upsert_cashbook(
        date=date(2024, 1, 2), cash_start=5000.0, cash_end=4000.0, invested_value=1100.0,
        total_nav=5100.0, voo_nav=5050.0, regime="RISK_ON", exposure_pct=0.2,
    )
    storage.upsert_cashbook(
        date=date(2024, 1, 2), cash_start=5000.0, cash_end=3900.0, invested_value=1300.0,
        total_nav=5200.0, voo_nav=5050.0, regime="RISK_ON", exposure_pct=0.26, voo_price=480.0,
    )
    history = storage.get_cashbook()
    assert len(history) == 1
    assert history[0].total_nav == 5200.0
    assert history[0].voo_price == 480.0
    assert storage.latest_cashbook() is not None
