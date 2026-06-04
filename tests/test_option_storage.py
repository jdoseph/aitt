"""Option-engine storage tables (Session 16)."""

from __future__ import annotations

from datetime import date

from src.core.storage import OptionTrade, Storage


def test_option_trade_roundtrip_and_status_filter(storage: Storage) -> None:
    pending = storage.add_option_trade(
        OptionTrade(
            ticker="nvda", strategy="composite", status="PENDING",
            option_type="call", strike=95.0, expiry=date(2024, 4, 19),
            dte_at_entry=45, contracts=2, multiplier=100, entry_iv=0.33,
            entry_delta=0.60, price_source="model", cost_basis=1480.0,
            underlying_stop=90.0, underlying_target=120.0,
            signal_snapshot_json='{"composite": 80}',
        )
    )
    assert pending.trade_id is not None
    assert pending.ticker == "NVDA"
    assert len(storage.get_option_trades(status="PENDING")) == 1
    assert storage.get_option_trades(status="OPEN") == []

    pending.status = "OPEN"
    pending.entry_premium = 7.40
    storage.update_option_trade(pending)
    reloaded = storage.get_option_trade(pending.trade_id)
    assert reloaded is not None and reloaded.status == "OPEN"
    assert reloaded.entry_premium == 7.40


def test_option_cashbook_upsert_idempotent(storage: Storage) -> None:
    storage.upsert_option_cashbook(
        date=date(2024, 1, 2), total_nav=5100.0, voo_nav=5050.0,
        invested_value=1500.0, regime="RISK_ON", voo_price=480.0,
    )
    storage.upsert_option_cashbook(
        date=date(2024, 1, 2), total_nav=5200.0, voo_nav=5050.0,
        invested_value=1600.0, regime="RISK_ON", voo_price=481.0,
    )
    hist = storage.get_option_cashbook()
    assert len(hist) == 1
    assert hist[0].total_nav == 5200.0
    assert storage.latest_option_cashbook() is not None
