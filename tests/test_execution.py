"""Price-simulation tests (Session 15): slippage tiers, gap protection, volume adj."""

from __future__ import annotations

from datetime import date

import pandas as pd

from src.core import execution as ex


# --- slippage tiers --------------------------------------------------------- #
def test_market_cap_tier_by_size() -> None:
    assert ex.market_cap_tier("NVDA", market_cap=100e9) == "large"
    assert ex.market_cap_tier("ANET", market_cap=30e9) == "mid"
    assert ex.market_cap_tier("CRDO", market_cap=5e9) == "small"


def test_volatile_tickers_override_market_cap() -> None:
    # RDW is on the volatile list — even a large notional cap keeps it volatile.
    assert ex.market_cap_tier("RDW", market_cap=80e9) == "volatile"


def test_unknown_market_cap_defaults_to_mid() -> None:
    assert ex.market_cap_tier("ZZZZ", market_cap=None) == "mid"


def test_tier_slippage_bps_entry_vs_exit() -> None:
    assert ex.tier_slippage_bps("large", ex.BUY) == 3.0
    assert ex.tier_slippage_bps("large", ex.SELL) == 3.0
    assert ex.tier_slippage_bps("small", ex.BUY) == 12.0
    # volatile is asymmetric: wider on the exit
    assert ex.tier_slippage_bps("volatile", ex.BUY) == 20.0
    assert ex.tier_slippage_bps("volatile", ex.SELL) == 25.0


def test_volume_adjustment_adds_bps_for_large_positions() -> None:
    # 2% of ADV (> 1% threshold) => +5 bps over the mid-cap base of 7.
    big = ex.slippage_bps(
        "ANET", ex.BUY, market_cap=30e9, position_dollars=2000.0, adv_dollars=100_000.0
    )
    assert big == 7.0 + 5.0
    # 0.5% of ADV (< threshold) => no adjustment.
    small = ex.slippage_bps(
        "ANET", ex.BUY, market_cap=30e9, position_dollars=500.0, adv_dollars=100_000.0
    )
    assert small == 7.0


# --- apply slippage --------------------------------------------------------- #
def test_apply_slippage_buy_pays_up_sell_receives_less() -> None:
    assert ex.apply_slippage(100.0, 10.0, ex.BUY) == 100.1  # +10 bps
    assert ex.apply_slippage(100.0, 10.0, ex.SELL) == 99.9  # -10 bps


# --- gap protection --------------------------------------------------------- #
def test_gap_protection_sell_fills_at_worse_of_stop_and_open() -> None:
    # Stop at 19.50 but the session gaps to a 17.00 open => fill at 17.00.
    assert ex.check_gap(19.50, 17.00, ex.SELL) == 17.00
    # No adverse gap (open above the stop) => fill at the stop level.
    assert ex.check_gap(19.50, 21.00, ex.SELL) == 19.50


def test_gap_protection_buy_fills_at_worse_of_expected_and_open() -> None:
    # Entry expected at 100 but gaps up to 105 => pay 105.
    assert ex.check_gap(100.0, 105.0, ex.BUY) == 105.0
    assert ex.check_gap(100.0, 98.0, ex.BUY) == 100.0


# --- open-price extraction (injected fetcher) ------------------------------- #
def test_get_open_price_uses_session_open() -> None:
    df = pd.DataFrame(
        {"open": [10.0, 11.0], "high": [0, 0], "low": [0, 0], "close": [0, 0], "volume": [0, 0]},
        index=pd.to_datetime(["2024-01-02", "2024-01-03"]),
    )
    price = ex.get_open_price("NVDA", date(2024, 1, 3), fetch=lambda t: df)
    assert price == 11.0
