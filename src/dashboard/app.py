"""Streamlit entry point.

Run with:  streamlit run src/dashboard/app.py

Uses st.navigation with callable pages (no auto-scan of the pages/ dir), so the
sidebar nav is defined explicitly here and each page module stays a plain
render() function.
"""

from __future__ import annotations

import streamlit as st

from src.dashboard.components import data
from src.dashboard.pages import alerts, backtest, chart, overview, portfolio, value_chain

st.set_page_config(page_title="AI Infra Tracker", page_icon="📡", layout="wide")


def _sidebar() -> None:
    with st.sidebar:
        st.markdown("### 📡 AI Infra Tracker")
        st.caption("AI data-center value-chain entry scanner")
        try:
            df = data.overview_table()
            n = len(df)
            n_alerts = len(data.alerts_table())
            bar_dates = data.get_store().get_signals()
            last = max((s.date for s in bar_dates), default=None)
            st.caption(f"{n} tickers · {n_alerts} alerts · data {last or 'none'}")
        except Exception as exc:  # noqa: BLE001 - sidebar status is best-effort
            st.caption(f"status unavailable: {exc}")
        if st.button("🔄 Refresh data"):
            data.refresh()
            st.rerun()


def main() -> None:
    _sidebar()
    # Explicit url_path per page — all render fns share the name "render", so
    # Streamlit would otherwise infer the same (colliding) URL path for each.
    nav = st.navigation(
        [
            st.Page(overview.render, title="Overview", icon="📊", url_path="overview", default=True),
            st.Page(chart.render, title="Chart", icon="📈", url_path="chart"),
            st.Page(value_chain.render, title="Value Chain", icon="🔗", url_path="value_chain"),
            st.Page(portfolio.render, title="Portfolio", icon="💼", url_path="portfolio"),
            st.Page(backtest.render, title="Backtest", icon="📉", url_path="backtest"),
            st.Page(alerts.render, title="Alerts", icon="🔔", url_path="alerts"),
        ]
    )
    nav.run()


main()
