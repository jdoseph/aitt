"""Market-data access.

yfinance is the only source for v1 (resolved decision), but all callers go
through :func:`fetch_prices` / :func:`fetch_many`, so an Alpha Vantage or
Polygon fallback can be slotted in later without touching the rest of the code.

All frames are normalized to a tz-naive ``DatetimeIndex`` named ``date`` with
lowercase columns ``open, high, low, close, volume``.
"""

from __future__ import annotations

import time
from typing import Final

import pandas as pd
import yfinance as yf
from loguru import logger

from src.core.config import settings

PRICE_COLUMNS: Final[list[str]] = ["open", "high", "low", "close", "volume"]


class DataFetchError(RuntimeError):
    """Raised when price data for a ticker cannot be retrieved or is unusable."""


def _bars_to_period(bars: int) -> str:
    """Pick a yfinance ``period`` string that comfortably covers ``bars`` daily candles.

    ~252 trading days per year, so add headroom and round up to whole years.
    """
    years = max(1, (bars // 250) + 1)
    if years <= 1:
        return "1y"
    if years <= 2:
        return "2y"
    if years <= 5:
        return "5y"
    return "max"


def _normalize(df: pd.DataFrame, bars: int) -> pd.DataFrame:
    """Lowercase columns, keep OHLCV, strip tz, sort, and trim to the last ``bars``."""
    if df is None or df.empty:
        raise DataFetchError("empty frame")

    df = df.rename(columns=str.lower)
    missing = [c for c in PRICE_COLUMNS if c not in df.columns]
    if missing:
        raise DataFetchError(f"missing columns {missing}")

    df = df[PRICE_COLUMNS].copy()

    # Normalize the index to tz-naive daily timestamps named "date".
    idx = pd.to_datetime(df.index)
    if isinstance(idx, pd.DatetimeIndex) and idx.tz is not None:
        idx = idx.tz_localize(None)
    df.index = pd.DatetimeIndex(idx).normalize()
    df.index.name = "date"

    df = df[~df.index.duplicated(keep="last")].sort_index()
    df = df.dropna(subset=["close"])
    if df.empty:
        raise DataFetchError("no rows after cleaning")
    return df.tail(bars)


def fetch_prices(ticker: str, bars: int | None = None) -> pd.DataFrame:
    """Fetch the last ``bars`` daily OHLCV candles for ``ticker`` (split/div adjusted).

    Retries with exponential backoff on transient failures.

    Raises:
        DataFetchError: if data cannot be retrieved after all retries.
    """
    bars = bars or settings.history_bars
    period = _bars_to_period(bars)
    last_err: Exception | None = None

    for attempt in range(1, settings.fetch_max_retries + 1):
        try:
            raw = yf.Ticker(ticker).history(
                period=period, interval="1d", auto_adjust=True, raise_errors=True
            )
            return _normalize(raw, bars)
        except DataFetchError as exc:
            # Normalization rejected the payload — likely a bad/delisted symbol.
            # Don't burn retries; surface immediately.
            raise DataFetchError(f"{ticker}: {exc}") from exc
        except Exception as exc:  # network / yfinance internal errors are retryable
            last_err = exc
            wait = settings.fetch_retry_backoff_sec * attempt
            logger.warning(
                "fetch {} attempt {}/{} failed: {} — retrying in {:.1f}s",
                ticker,
                attempt,
                settings.fetch_max_retries,
                exc,
                wait,
            )
            if attempt < settings.fetch_max_retries:
                time.sleep(wait)

    raise DataFetchError(f"{ticker}: failed after {settings.fetch_max_retries} attempts: {last_err}")


def fetch_many(
    tickers: list[str],
    bars: int | None = None,
    pause_sec: float = 0.3,
) -> dict[str, pd.DataFrame]:
    """Fetch many tickers sequentially, skipping (and logging) any that fail.

    A small pause between requests is polite to Yahoo's endpoint. Returns a dict
    of only the tickers that fetched successfully — callers decide how to react
    to gaps.
    """
    out: dict[str, pd.DataFrame] = {}
    for i, t in enumerate(tickers):
        try:
            out[t] = fetch_prices(t, bars)
        except DataFetchError as exc:
            logger.error("skipping {}: {}", t, exc)
        if pause_sec and i < len(tickers) - 1:
            time.sleep(pause_sec)
    logger.info("fetched {}/{} tickers", len(out), len(tickers))
    return out
