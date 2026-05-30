"""Next-earnings-date lookup via yfinance (best-effort, cached per day).

The network call is isolated in `_next_earnings_date`; the pure `days_until`
helper is what the scorecard uses, so the date math is testable without yfinance.
yfinance's earnings calendar is occasionally missing/stale — every public
function degrades to ``None`` rather than raising.
"""

from __future__ import annotations

from datetime import date

from loguru import logger


def days_until(target: date, today: date | None = None) -> int | None:
    """Calendar days from ``today`` to ``target``; None if the date is in the past."""
    today = today or date.today()
    delta = (target - today).days
    return delta if delta >= 0 else None


# (ticker, today) -> next earnings date or None
_cache: dict[tuple[str, date], date | None] = {}


def _next_earnings_date(ticker: str) -> date | None:
    """Next future earnings date from yfinance, or None if unavailable."""
    try:
        import yfinance as yf

        df = yf.Ticker(ticker).get_earnings_dates(limit=12)
        if df is None or df.empty:
            return None
        today = date.today()
        future = [idx.date() for idx in df.index if idx.date() >= today]
        return min(future) if future else None
    except Exception as exc:  # noqa: BLE001 - flaky external calendar, best-effort
        logger.debug("earnings lookup failed for {}: {}", ticker, exc)
        return None


def days_to_earnings(ticker: str, today: date | None = None) -> int | None:
    """Calendar days to the next earnings date for ``ticker`` (None if unknown)."""
    today = today or date.today()
    key = (ticker.upper(), today)
    if key not in _cache:
        _cache[key] = _next_earnings_date(ticker)
    nxt = _cache[key]
    return days_until(nxt, today) if nxt else None
