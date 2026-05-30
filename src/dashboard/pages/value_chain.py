"""Value-chain page: tickers grouped by layer with per-layer signal density."""

from __future__ import annotations

import streamlit as st

from src.dashboard.components import data, theme


def render() -> None:
    st.title("🔗 Value Chain")
    df = data.overview_table()
    wl = data.get_watchlist()
    if df.empty:
        st.warning("No data yet. Run `python -m src.agent --once` to populate the database.")
        return

    # --- AI-thesis health + layer strength / rotation (Session 11) ---
    view = data.layer_strength_view()
    if view:
        thesis_label = data.thesis_summary(view)
        badge = "🟢" if thesis_label.startswith("Healthy") else "🔴"
        st.markdown(f"### AI-thesis health: {badge} {thesis_label}")
        rows = view.get("rows")
        if rows is not None and not getattr(rows, "empty", True):
            st.caption("Layer strength (0–100) and rotation Δ vs the prior cycle (▲ in / ▼ out).")
            st.dataframe(
                rows,
                hide_index=True,
                use_container_width=True,
                column_config={
                    "strength": st.column_config.ProgressColumn(
                        "strength", min_value=0, max_value=100, format="%.0f"
                    ),
                },
            )
        st.divider()

    st.caption(
        "Each layer shows how many of its names are at/approaching an entry "
        "(at EMA, ATH entry zone, or a breakout)."
    )

    entry_label_parts = [theme.status_label(s) for s in sorted(theme.ENTRY_STATUSES)]

    for layer_key, title in wl.layers.items():
        sub = df[df["layer"] == layer_key]
        if sub.empty:
            continue
        # Count tickers whose EMA/ATH/FLAG/IPO cell reflects an entry status.
        entry_count = 0
        for _, row in sub.iterrows():
            cells = " ".join(str(row[c]).lower() for c in ("EMA", "ATH", "FLAG", "IPO"))
            if any(k in cells for k in ("entry zone", "at 21 ema", "at 9 ema", "breakout")):
                entry_count += 1

        color = theme.layer_color(layer_key)
        header = (
            f"<span style='display:inline-block;width:10px;height:10px;border-radius:50%;"
            f"background:{color};margin-right:8px'></span>"
            f"<b>{title}</b> — {len(sub)} names · "
            f"<span style='color:{color}'>{entry_count} at/approaching entry</span>"
        )
        st.markdown(header, unsafe_allow_html=True)

        with st.expander("show tickers", expanded=entry_count > 0):
            ordered = sub.sort_values("conf", ascending=False)
            st.dataframe(
                ordered[["ticker", "name", "price", "chg_%", "EMA", "ATH", "FLAG", "stars"]],
                hide_index=True,
                use_container_width=True,
            )
        st.divider()
