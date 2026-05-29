"""Alerts page: chronological log with filters and acknowledge/dismiss."""

from __future__ import annotations

import streamlit as st

from src.dashboard.components import data


def render() -> None:
    st.title("🔔 Alerts")
    df = data.alerts_table()
    if df.empty:
        st.info("No alerts yet. Run `python -m src.agent --once` to generate some.")
        return

    c1, c2, c3, c4 = st.columns([1.8, 2, 1.2, 1.4])
    with c1:
        strategies = sorted(df["strategy"].unique())
        pick_strat = st.multiselect("Strategy", strategies, default=[])
    with c2:
        layers = sorted(t for t in df["layer_title"].unique() if t)
        pick_layers = st.multiselect("Layer", layers, default=[])
    with c3:
        min_conf = st.slider("Min ⭐", 0, 3, 0)
    with c4:
        show = st.radio("Show", ["Unacknowledged", "All"], horizontal=False)

    view = df.copy()
    if pick_strat:
        view = view[view["strategy"].isin(pick_strat)]
    if pick_layers:
        view = view[view["layer_title"].isin(pick_layers)]
    if min_conf:
        view = view[view["conf"] >= min_conf]
    if show == "Unacknowledged":
        view = view[~view["acknowledged"]]

    st.caption(f"{len(view)} alerts")
    st.dataframe(
        view[["date", "ticker", "strategy", "status", "stars", "message", "acknowledged"]],
        hide_index=True,
        use_container_width=True,
        height=min(640, 80 + 34 * len(view)),
    )

    # --- acknowledge / dismiss ---
    open_ids = view.loc[~view["acknowledged"], "id"].tolist()
    if open_ids:
        st.subheader("Acknowledge")
        labels = {
            int(r["id"]): f"{r['date']} · {r['ticker']} · {r['status']} {r['stars']}"
            for _, r in view[~view["acknowledged"]].iterrows()
        }
        chosen = st.multiselect(
            "Select alerts to acknowledge", options=list(labels), format_func=lambda i: labels[i]
        )
        a1, a2 = st.columns(2)
        with a1:
            if st.button("✓ Acknowledge selected", disabled=not chosen):
                n = data.acknowledge([int(i) for i in chosen])
                st.success(f"Acknowledged {n} alert(s).")
                st.rerun()
        with a2:
            if st.button("✓ Acknowledge ALL shown"):
                n = data.acknowledge([int(i) for i in open_ids])
                st.success(f"Acknowledged {n} alert(s).")
                st.rerun()
    else:
        st.success("Nothing outstanding — all shown alerts acknowledged.")
