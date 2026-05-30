"""Weekly trend alignment tests (Session 12)."""

from __future__ import annotations

from src.core import multitimeframe as mtf
from src.core.strategies.base import Signal
from tests.factories import make_ohlcv


def _daily(closes: list[float]) -> "object":
    return make_ohlcv(closes)


def test_to_weekly_aggregates_five_trading_days() -> None:
    # 10 business days -> 2 full weeks (plus the partial first/last depending on cal).
    df = _daily([100.0 + i for i in range(10)])
    weekly = mtf.to_weekly(df)
    assert len(weekly) <= 3  # collapsed from 10 daily bars
    # Weekly high is the max of its daily highs.
    assert weekly["high"].iloc[0] >= df["high"].iloc[0]
    assert weekly["volume"].iloc[0] >= df["volume"].iloc[0]


def test_weekly_trend_uptrend_on_long_rally() -> None:
    # ~250 trading days rising -> well above a rising 30-week MA.
    df = _daily([100.0 + i for i in range(250)])
    wt = mtf.weekly_trend(df)
    assert wt.trend == mtf.UPTREND
    assert wt.above_ma is True
    assert wt.slope_pct is not None and wt.slope_pct > 0


def test_weekly_trend_downtrend_on_long_decline() -> None:
    df = _daily([400.0 - i for i in range(250)])
    wt = mtf.weekly_trend(df)
    assert wt.trend == mtf.DOWNTREND
    assert wt.above_ma is False


def test_weekly_trend_neutral_when_thin() -> None:
    df = _daily([100.0 + i for i in range(40)])  # < 30 weeks of data
    wt = mtf.weekly_trend(df)
    assert wt.trend == mtf.NEUTRAL
    assert wt.above_ma is None


def test_alignment_flags() -> None:
    up = _daily([100.0 + i for i in range(250)])
    down = _daily([400.0 - i for i in range(250)])
    sig = Signal("T", "ema_pullback", "AT_21_EMA")
    assert mtf.alignment(mtf.weekly_trend(up), sig) == mtf.ALIGNED
    assert mtf.alignment(mtf.weekly_trend(down), sig) == mtf.COUNTER
