"""Live option-chain fetch via yfinance (Session 16) — forward-only.

This is the ONLY network piece of the options layer, and it is consulted only at
entry. It returns ``None`` whenever a usable chain isn't available (no expiries,
thin open interest, or any provider error), so callers fall back to the model.
``ticker_factory`` is injected in tests to stay offline.
"""

from __future__ import annotations

from datetime import date as Date
from datetime import datetime
from typing import Any, Callable

from loguru import logger

from src.core.config import settings


def _nearest_expiry(expiries: tuple[str, ...], target_dte: int, as_of: Date) -> str | None:
    best, best_gap = None, 10**9
    for e in expiries:
        try:
            d = datetime.strptime(e, "%Y-%m-%d").date()
        except ValueError:
            continue
        gap = abs((d - as_of).days - target_dte)
        if gap < best_gap:
            best_gap, best = gap, e
    return best


def fetch_chain(
    ticker: str,
    *,
    target_dte: int,
    as_of: Date,
    ticker_factory: Callable[[str], Any] | None = None,
    min_oi: int | None = None,
) -> dict[str, Any] | None:
    """Return ``{expiry, calls:[{strike,bid,ask,iv,open_interest}]}`` or None.

    A chain is "usable" only if at least one call has open interest >= ``min_oi``.
    """
    min_oi = min_oi if min_oi is not None else settings.option_chain_min_oi
    if ticker_factory is None:
        import yfinance as yf

        ticker_factory = yf.Ticker
    try:
        tk = ticker_factory(ticker)
        expiries = tuple(getattr(tk, "options", ()) or ())
        if not expiries:
            return None
        chosen = _nearest_expiry(expiries, target_dte, as_of)
        if chosen is None:
            return None
        oc = tk.option_chain(chosen)
        calls_df = oc.calls
        if calls_df is None or calls_df.empty:
            return None
        calls = []
        for _, row in calls_df.iterrows():
            oi = int(row.get("openInterest", 0) or 0)
            calls.append(
                {
                    "strike": float(row["strike"]),
                    "bid": float(row.get("bid", 0.0) or 0.0),
                    "ask": float(row.get("ask", 0.0) or 0.0),
                    "iv": float(row.get("impliedVolatility", 0.0) or 0.0),
                    "open_interest": oi,
                }
            )
        if not any(c["open_interest"] >= min_oi for c in calls):
            return None
        return {"expiry": datetime.strptime(chosen, "%Y-%m-%d").date(), "calls": calls}
    except Exception as exc:  # noqa: BLE001 - chain is best-effort; model is the fallback
        logger.warning("option-chain fetch failed for {}: {}", ticker, exc)
        return None
