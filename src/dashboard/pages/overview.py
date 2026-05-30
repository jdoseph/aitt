"""Overview page: sortable, filterable table of every ticker."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.dashboard.components import data, scorecard, theme

_SORTS = {
    "Setup quality": ("quality_rank", False),
    "Confidence (⭐ first)": ("conf", False),
    "Closest to 21 EMA": ("abs_dist_21", True),
    "Closest to ATH entry": ("ath_entry_gap", True),
    "% change today": ("chg_%", False),
    "Ticker (A–Z)": ("ticker", True),
}


def render() -> None:
    st.title("📊 Overview")
    df = data.overview_table()
    if df.empty:
        st.warning("No data yet. Run `python -m src.agent --once` to populate the database.")
        return

    regime = data.latest_regime()
    if regime is not None:
        badge = {"RISK_ON": "🟢 RISK_ON", "NEUTRAL": "🟡 NEUTRAL", "RISK_OFF": "🔴 RISK_OFF"}.get(
            regime.label, regime.label
        )
        st.markdown(f"### Market regime: {badge}")
        st.caption(regime.summary)

    ctx = data.market_context()
    if ctx is not None:
        scorecard.render_market_header(ctx, data.get_watchlist())
        st.divider()

    # Derived sort helpers.
    df["abs_dist_21"] = df["dist_21_%"].abs()
    # Distance from the middle of the 5–10% ATH entry zone (smaller = closer to ideal entry).
    df["ath_entry_gap"] = (df["pullback_%"] - 7.5).abs()

    layers = sorted(df["layer_title"].unique())
    strat_cols = ["EMA", "ATH", "FLAG", "IPO"]

    c1, c2, c3, c4 = st.columns([2.2, 2.2, 1.6, 1.4])
    with c1:
        pick_layers = st.multiselect("Value-chain layer", layers, default=[])
    with c2:
        query = st.text_input("Filter by status text (e.g. 'entry', 'breakout')", "")
    with c3:
        min_conf = st.slider("Min ⭐", 0, 3, 0)
    with c4:
        sort_label = st.selectbox("Sort by", list(_SORTS), index=0)

    view = df.copy()
    if pick_layers:
        view = view[view["layer_title"].isin(pick_layers)]
    if min_conf:
        view = view[view["conf"] >= min_conf]
    if query:
        q = query.lower()
        mask = pd.Series(False, index=view.index)
        for col in strat_cols:
            mask |= view[col].str.lower().str.contains(q, na=False)
        view = view[mask]

    sort_col, asc = _SORTS[sort_label]
    view = view.sort_values(sort_col, ascending=asc, na_position="last")

    st.caption(f"{len(view)} of {len(df)} tickers")
    display_cols = [
        "ticker", "name", "layer_title", "price", "chg_%",
        "dist_9_%", "dist_21_%", "pullback_%", "EMA", "ATH", "FLAG", "IPO", "stars", "action",
        "disqualified", "strongest_bear",
    ]
    st.dataframe(
        view[display_cols],
        hide_index=True,
        use_container_width=True,
        height=min(720, 80 + 35 * len(view)),
        column_config={
            "layer_title": st.column_config.TextColumn("layer"),
            "chg_%": st.column_config.NumberColumn("chg %", format="%.2f"),
            "dist_9_%": st.column_config.NumberColumn("Δ9 %", format="%.2f"),
            "dist_21_%": st.column_config.NumberColumn("Δ21 %", format="%.2f"),
            "pullback_%": st.column_config.NumberColumn("Δ ATH %", format="%.2f"),
            "price": st.column_config.NumberColumn("price", format="%.2f"),
            "disqualified": st.column_config.TextColumn("🚫 disqualified"),
            "strongest_bear": st.column_config.TextColumn("⛔ top bear factor"),
        },
    )
    st.caption(
        "Δ9 / Δ21 = % distance to the 9 / 21 EMA · Δ ATH = % below all-time high · "
        "FLAG shows days-in-range / width when consolidating."
    )
