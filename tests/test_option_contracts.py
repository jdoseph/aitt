"""Contract model + strike/expiry selection (Session 16)."""

from __future__ import annotations

from datetime import date

import pandas as pd

from src.core.options.contracts import OptionContract, select_contract


def _frame(close: float, n: int = 60) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {"open": [close] * n, "high": [close] * n, "low": [close] * n,
         "close": [close] * n, "volume": [1_000_000] * n},
        index=idx,
    )


def test_select_contract_model_fallback_picks_dte_and_delta() -> None:
    # No live chain -> model path. ~0.60-delta call is slightly in-the-money,
    # so the chosen strike should sit below spot.
    df = _frame(100.0)
    c = select_contract(
        "NVDA", df, as_of=date(2024, 3, 1),
        chain=None, target_delta=0.60, target_dte=45, iv=0.30,
    )
    assert isinstance(c, OptionContract)
    assert c.source == "model"
    assert c.strike < 100.0  # ITM for ~0.60 delta
    assert 30 <= c.dte <= 60
    assert 0.45 < c.delta < 0.75


def test_select_contract_uses_live_chain_when_present() -> None:
    df = _frame(100.0)
    chain = {
        "expiry": date(2024, 4, 19),
        "calls": [
            {"strike": 95.0, "bid": 7.0, "ask": 7.4, "iv": 0.33, "open_interest": 500, "delta": 0.62},
            {"strike": 105.0, "bid": 2.0, "ask": 2.2, "iv": 0.31, "open_interest": 800, "delta": 0.40},
        ],
    }
    c = select_contract(
        "NVDA", df, as_of=date(2024, 3, 1),
        chain=chain, target_delta=0.60, target_dte=45, iv=0.33,
    )
    assert c.source == "chain"
    assert c.strike == 95.0  # nearest the 0.60 delta target
    assert c.expiry == date(2024, 4, 19)
