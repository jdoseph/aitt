"""Helpers for building deterministic synthetic OHLCV frames in tests."""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd


def make_ohlcv(
    closes: Sequence[float],
    *,
    highs: Sequence[float] | None = None,
    lows: Sequence[float] | None = None,
    opens: Sequence[float] | None = None,
    volumes: Sequence[float] | None = None,
    start: str = "2025-01-01",
) -> pd.DataFrame:
    """Build a date-indexed OHLCV frame from a close series.

    Highs/lows/opens default to a tight band around close; volume defaults flat.
    """
    n = len(closes)
    idx = pd.date_range(start, periods=n, freq="B", name="date")
    closes = list(closes)
    opens = list(opens) if opens is not None else closes
    highs = list(highs) if highs is not None else [c * 1.005 for c in closes]
    lows = list(lows) if lows is not None else [c * 0.995 for c in closes]
    volumes = list(volumes) if volumes is not None else [1_000_000.0] * n
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=idx,
    )
