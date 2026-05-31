"""Portfolio page — paper NAV vs VOO, exposure dial, holdings, suggestions (Session 13).

Everything here is a SIMULATED / PAPER portfolio: target weights and rebalance
suggestions against a hypothetical balance, never executed. The NAV-vs-VOO overlay
is the whole point — the book is judged against the index it's trying to beat.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import pandas as pd
import streamlit as st

from src.core.config import settings
from src.core.storage import PortfolioSnapshot
from src.dashboard.components.data import get_store

_DIAL = {"RISK_ON": "🟢 RISK_ON", "NEUTRAL": "🟡 NEUTRAL", "RISK_OFF": "🔴 RISK_OFF"}


def render() -> None:
    st.header("💼 Portfolio (paper)")
    st.caption(
        "Simulated book — dynamic exposure + conviction concentration + RS rotation. "
        "All suggestions, never executed."
    )

    store = get_store()
    history = store.get_portfolio_history()
    latest = store.latest_portfolio_snapshot()

    if latest is None:
        st.info("No portfolio snapshots yet. Run the agent: `python -m src.agent --once`.")
        return

    # --- exposure dial + NAV headline ---
    start = settings.paper_start_balance
    total_return_pct = (latest.nav / start - 1.0) * 100.0 if start else 0.0
    c1, c2, c3 = st.columns(3)
    c1.metric("Exposure", f"{latest.exposure * 100:.0f}%", _DIAL.get(latest.regime, latest.regime))
    c2.metric("Paper NAV", f"${latest.nav:,.0f}", f"{total_return_pct:+.1f}% vs start")
    c3.metric("Start balance", f"${start:,.0f}")

    # --- NAV vs VOO overlay (both normalized to the start) ---
    chart_df = _nav_vs_benchmark(history)
    if chart_df is not None and not chart_df.empty:
        st.subheader("Paper NAV vs VOO (indexed to 100)")
        st.line_chart(chart_df)
    else:
        st.caption("NAV history will chart once a benchmark (VOO) close has been recorded.")

    # --- current holdings ---
    st.subheader("Holdings")
    weights = json.loads(latest.weights or "{}")
    if weights:
        rows = [
            {"Ticker": t, "Weight": f"{w * 100:.0f}%"}
            for t, w in sorted(weights.items(), key=lambda kv: -kv[1])
        ]
        cash_pct = max(0.0, 1.0 - sum(weights.values())) * 100.0
        rows.append({"Ticker": "CASH", "Weight": f"{cash_pct:.0f}%"})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.caption("Fully in cash — no positions held.")

    # --- rebalance suggestions ---
    st.subheader("Rebalance suggestions")
    st.caption("Paper-only — these are never auto-executed.")
    suggestions = json.loads(latest.suggestions or "[]")
    if suggestions:
        for s in suggestions:
            st.write(f"• {s}")
    else:
        st.caption("No changes suggested this cycle (within the no-trade band).")


def _nav_vs_benchmark(history: Sequence[PortfolioSnapshot]) -> pd.DataFrame | None:
    """Index NAV and the benchmark to 100 at the first day with a benchmark value."""
    records = [(h.date, h.nav, h.benchmark_value) for h in history]
    if not records:
        return None
    df = pd.DataFrame(records, columns=["date", "NAV", "bench"]).set_index("date")
    bench_valid = df[df["bench"] > 0]
    out = pd.DataFrame(index=df.index)
    nav0 = df["NAV"].iloc[0]
    out["Paper NAV"] = df["NAV"] / nav0 * 100.0 if nav0 else df["NAV"]
    if not bench_valid.empty:
        b0 = bench_valid["bench"].iloc[0]
        out["VOO"] = df["bench"].where(df["bench"] > 0) / b0 * 100.0
    return out
