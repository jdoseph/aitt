"""Chart page: per-ticker candlestick with all indicators."""

from __future__ import annotations

import json

import streamlit as st

from src.dashboard.components import charts, data, theme


def render() -> None:
    st.title("📈 Chart")
    wl = data.get_watchlist()
    tickers = wl.tickers
    if not tickers:
        st.warning("Watchlist is empty.")
        return

    c1, c2 = st.columns([3, 1])
    with c1:
        ticker = st.selectbox(
            "Ticker",
            tickers,
            format_func=lambda t: f"{t} — {next((e.name for e in wl.entries if e.ticker == t), t)}",
        )
    with c2:
        last_n = st.select_slider("Days shown", [60, 90, 120, 180, 252], value=90)

    df = data.ticker_prices(ticker)
    if df.empty:
        st.warning(f"No price data for {ticker}. Run the agent to fetch it.")
        return

    sigs = data.latest_signals(ticker)
    alerts = data.alert_dates_for(ticker)

    # Per-strategy status line.
    cols = st.columns(4)
    for col, strat in zip(cols, ("ema_pullback", "ath_pullback", "consolidation_breakout", "ipo_base")):
        rec = sigs.get(strat)
        label = theme.STRATEGY_LABELS.get(strat, strat)
        if rec:
            col.metric(label, theme.status_label(rec.status), theme.stars(rec.confidence) or None)
        else:
            col.metric(label, "—")

    fig = charts.build_price_chart(ticker, df, sigs, alerts, last_n=int(last_n))
    st.plotly_chart(fig, use_container_width=True)

    with st.expander("Latest signal details"):
        for strat, rec in sigs.items():
            st.write(
                f"**{theme.STRATEGY_LABELS.get(strat, strat)}** — {rec.status} "
                f"{theme.stars(rec.confidence)}  ·  patterns: {json.loads(rec.patterns or '[]')}"
            )
            st.json(json.loads(rec.details or "{}"), expanded=False)
