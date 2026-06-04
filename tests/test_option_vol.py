"""Realized-volatility proxy (Session 16)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.core.options import vol


def _frame(closes: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="B")
    return pd.DataFrame({"close": closes}, index=idx)


def test_realized_vol_constant_series_is_zero() -> None:
    df = _frame([100.0] * 40)
    assert vol.realized_vol(df, window=20) == pytest.approx(0.0)


def test_realized_vol_is_annualized_and_scaled() -> None:
    rng = np.random.default_rng(0)
    # ~1% daily moves -> annualized ~ 0.01*sqrt(252) ~= 0.159, x1.1 premium.
    closes = [100.0]
    for r in rng.normal(0.0, 0.01, 260):
        closes.append(closes[-1] * (1.0 + r))
    sigma = vol.realized_vol(_frame(closes), window=30, premium_mult=1.1)
    assert 0.10 < sigma < 0.30


def test_realized_vol_thin_history_returns_fallback() -> None:
    df = _frame([100.0, 101.0])  # fewer than window+1 rows
    assert vol.realized_vol(df, window=20, fallback=0.5) == 0.5
