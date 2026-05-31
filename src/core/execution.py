"""Price simulation for the autonomous paper engine (Session 15).

Honest, *estimated* fills — never real orders:

* tiered slippage by liquidity (large/mid/small/volatile) + a volume adjustment,
* gap protection so a queued exit fills at the worse of its level and the actual
  open (a stop at $19.50 that gaps to a $17.00 open fills at $17.00),
* next-open / latest-price helpers over the yfinance seam (injectable for tests).

All slippage is an approximation: real exchange fills, partial fills, and market
impact are not modeled. yfinance intraday data is ~15 min delayed, so live stop
surveillance would be tighter than this simulation.
"""

from __future__ import annotations

from datetime import date as Date
from typing import Callable, Literal

import pandas as pd
from loguru import logger

from src.core.config import settings

Side = Literal["BUY", "SELL"]
BUY: Side = "BUY"
SELL: Side = "SELL"

Tier = Literal["large", "mid", "small", "volatile"]


def market_cap_tier(ticker: str, market_cap: float | None = None) -> Tier:
    """Classify a name's liquidity tier.

    Volatile/micro names (config list) override market cap. Otherwise the tier
    follows the market-cap thresholds; an unknown cap defaults to ``mid``.
    """
    if ticker.upper() in {t.upper() for t in settings.slippage_volatile_tickers}:
        return "volatile"
    if market_cap is None:
        return "mid"
    if market_cap >= settings.slippage_large_cap_usd:
        return "large"
    if market_cap >= settings.slippage_mid_cap_usd:
        return "mid"
    return "small"


def tier_slippage_bps(tier: Tier, side: Side) -> float:
    """Base slippage (bps) for a liquidity tier and side (volatile is asymmetric)."""
    if tier == "large":
        return settings.slippage_large_bps
    if tier == "mid":
        return settings.slippage_mid_bps
    if tier == "small":
        return settings.slippage_small_bps
    # volatile: wider, and wider still on the exit
    return (
        settings.slippage_volatile_entry_bps
        if side == BUY
        else settings.slippage_volatile_exit_bps
    )


def slippage_bps(
    ticker: str,
    side: Side,
    *,
    market_cap: float | None = None,
    position_dollars: float = 0.0,
    adv_dollars: float = 0.0,
) -> float:
    """Total estimated slippage (bps): the tier base plus a volume adjustment.

    When the position is larger than ``volume_slippage_pct`` of the 20-day average
    dollar volume, add ``volume_slippage_extra_bps`` (you move the tape).
    """
    tier = market_cap_tier(ticker, market_cap)
    bps = tier_slippage_bps(tier, side)
    if adv_dollars > 0 and position_dollars > settings.volume_slippage_pct * adv_dollars:
        bps += settings.volume_slippage_extra_bps
    return bps


def apply_slippage(price: float, bps: float, side: Side) -> float:
    """Apply slippage to a fill price — a buyer pays up, a seller receives less."""
    factor = 1.0 + bps / 10_000.0 if side == BUY else 1.0 - bps / 10_000.0
    return price * factor


def check_gap(expected_price: float, actual_open: float, side: Side) -> float:
    """Return the worse-for-the-trader of an expected fill and the actual open.

    A queued long exit (SELL) that gaps below its stop fills at the lower open; a
    queued entry (BUY) that gaps up fills at the higher open.
    """
    if side == SELL:
        return min(expected_price, actual_open)
    return max(expected_price, actual_open)


# --------------------------------------------------------------------------- #
# Price access over the yfinance seam (injectable for tests)
# --------------------------------------------------------------------------- #
def get_open_price(
    ticker: str,
    on: Date,
    *,
    fetch: Callable[[str], pd.DataFrame] | None = None,
) -> float | None:
    """The session open for ``ticker`` on ``on`` (None if unavailable).

    ``fetch`` returns a date-indexed OHLCV frame (defaults to the real fetcher).
    """
    df = _fetch(ticker, fetch)
    if df is None or df.empty or "open" not in df.columns:
        return None
    idx = pd.DatetimeIndex(df.index)
    mask = idx.normalize() == pd.Timestamp(on).normalize()
    if mask.any():
        return float(df.loc[mask, "open"].iloc[0])
    return None


def get_current_price(
    ticker: str,
    *,
    fetch: Callable[[str], pd.DataFrame] | None = None,
) -> float | None:
    """The latest available close for ``ticker`` (None if unavailable).

    Uses the most recent stored/fetched daily close. yfinance free data is
    ~15 min delayed, so intraday surveillance built on this is slightly stale.
    """
    df = _fetch(ticker, fetch)
    if df is None or df.empty or "close" not in df.columns:
        return None
    return float(df["close"].iloc[-1])


def _fetch(
    ticker: str, fetch: Callable[[str], pd.DataFrame] | None
) -> pd.DataFrame | None:
    if fetch is None:
        from src.core.data import fetch_prices

        fetch = fetch_prices
    try:
        return fetch(ticker)
    except Exception as exc:  # never let a flaky fetch crash a monitor cycle
        logger.warning(f"price fetch failed for {ticker}: {exc}")
        return None
