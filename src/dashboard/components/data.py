"""Cached data access for the dashboard.

The Storage/engine is a cached resource (one per process, cross-thread safe);
derived tables are cached data with a short TTL and a manual refresh hook.
"""

from __future__ import annotations

import json
from datetime import date as Date

import pandas as pd
import streamlit as st

from src.core import market
from src.core.indicators import compute_metrics
from src.core.market import MarketContext
from src.core.storage import DossierRecord, SignalRecord, Storage
from src.core.watchlist import Watchlist, load_watchlist
from src.dashboard.components import theme

_ACTION_RANK = {"HIGH-QUALITY": 3, "DECENT": 2, "MARGINAL": 1, "AVOID": 0}


def _best_action(sigs: dict[str, SignalRecord]) -> str:
    """Highest-graded scorecard action across a ticker's latest signals ('' if none)."""
    actions = []
    for rec in sigs.values():
        card = json.loads(rec.details or "{}").get("scorecard")
        if card and card.get("action"):
            actions.append(card["action"])
    return max(actions, key=lambda a: _ACTION_RANK.get(a, -1), default="")


@st.cache_resource
def get_store() -> Storage:
    return Storage(check_same_thread=False)


@st.cache_resource
def get_watchlist() -> Watchlist:
    return load_watchlist()


def refresh() -> None:
    """Clear cached data so the next read reflects the latest DB state."""
    st.cache_data.clear()


def _latest_signals(store: Storage, ticker: str) -> dict[str, SignalRecord]:
    """Most recent signal row per strategy for one ticker."""
    sigs = store.get_signals(ticker=ticker)
    if not sigs:
        return {}
    latest_date = max(s.date for s in sigs)
    return {s.strategy: s for s in sigs if s.date == latest_date}


@st.cache_data(ttl=300)
def overview_table() -> pd.DataFrame:
    """One row per ticker with price, distances, per-strategy status, and confidence."""
    store, wl = get_store(), get_watchlist()
    rows: list[dict[str, object]] = []

    for entry in wl.entries:
        df = store.get_prices(entry.ticker)
        if df.empty:
            continue
        m = compute_metrics(df)
        prev_close = float(df["close"].iloc[-2]) if len(df) >= 2 else m.close
        chg_pct = ((m.close - prev_close) / prev_close * 100) if prev_close else 0.0
        sigs = _latest_signals(store, entry.ticker)

        def stat(strategy: str) -> str:
            rec = sigs.get(strategy)
            return rec.status if rec else ""

        dossier = store.latest_dossier(entry.ticker)
        bear = dossier.strongest_bear if dossier else ""

        max_conf = max((s.confidence for s in sigs.values()), default=0)
        cons = sigs.get("consolidation_breakout")
        cons_txt = ""
        if cons and cons.status in ("CONSOLIDATING", "BREAKOUT", "BREAKDOWN"):
            import json

            d = json.loads(cons.details or "{}")
            cons_txt = f"{d.get('days_in_range', '?')}d / {d.get('range_width_pct', '?')}%"

        rows.append(
            {
                "ticker": entry.ticker,
                "name": entry.name,
                "layer": entry.layer,
                "layer_title": wl.layer_title(entry.layer),
                "price": round(m.close, 2),
                "chg_%": round(chg_pct, 2),
                "dist_9_%": None if m.dist_ema_9_pct is None else round(m.dist_ema_9_pct, 2),
                "dist_21_%": None if m.dist_ema_21_pct is None else round(m.dist_ema_21_pct, 2),
                "pullback_%": round(m.pullback_from_ath_pct, 2),
                "EMA": theme.status_label(stat("ema_pullback")),
                "ATH": theme.status_label(stat("ath_pullback")),
                "FLAG": cons_txt or theme.status_label(stat("consolidation_breakout")),
                "IPO": theme.status_label(stat("ipo_base")) if "ipo_base" in sigs else "",
                "conf": max_conf,
                "stars": theme.stars(max_conf),
                "action": _best_action(sigs),
                "strongest_bear": bear,
            }
        )

    df = pd.DataFrame(rows)
    if not df.empty:
        df["quality_rank"] = df["action"].map(lambda a: _ACTION_RANK.get(a, -1))
    return df


@st.cache_data(ttl=300)
def market_context() -> MarketContext | None:
    """Breadth + layer leadership computed from the latest stored signals."""
    store, wl = get_store(), get_watchlist()
    records: list[SignalRecord] = []
    for t in wl.tickers:
        records.extend(_latest_signals(store, t).values())
    if not records:
        return None
    return market.compute_context(records, wl)


@st.cache_data(ttl=300)
def ticker_prices(ticker: str) -> pd.DataFrame:
    return get_store().get_prices(ticker)


def latest_signals(ticker: str) -> dict[str, SignalRecord]:
    return _latest_signals(get_store(), ticker)


def latest_dossier(ticker: str) -> DossierRecord | None:
    return get_store().latest_dossier(ticker)


@st.cache_data(ttl=300)
def alerts_table() -> pd.DataFrame:
    """All alerts joined with ticker layer, newest first."""
    store, wl = get_store(), get_watchlist()
    layer_of = {e.ticker: e.layer for e in wl.entries}
    title_of = wl.layers
    rows: list[dict[str, object]] = []
    for a in store.get_alerts():
        layer = layer_of.get(a.ticker, "")
        rows.append(
            {
                "id": a.id,
                "date": a.date,
                "ticker": a.ticker,
                "strategy": theme.STRATEGY_LABELS.get(a.strategy, a.strategy),
                "status": a.status,
                "stars": theme.stars(a.confidence),
                "conf": a.confidence,
                "message": a.message,
                "layer": layer,
                "layer_title": title_of.get(layer, layer),
                "acknowledged": a.acknowledged,
            }
        )
    return pd.DataFrame(rows)


def acknowledge(alert_ids: list[int]) -> int:
    store = get_store()
    n = sum(1 for i in alert_ids if store.acknowledge_alert(i))
    refresh()
    return n


def alert_dates_for(ticker: str) -> list[tuple[Date, str, int]]:
    """(date, status, confidence) for each alert of a ticker — used for chart markers."""
    return [
        (a.date, a.status, a.confidence)
        for a in get_store().get_alerts()
        if a.ticker == ticker.upper()
    ]
