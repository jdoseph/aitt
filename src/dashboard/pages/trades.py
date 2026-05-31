"""Trades page (Session 15): the autonomous paper engine's book + journal.

A read-only window into a fully simulated account — the agent opens, monitors,
and closes these trades on its own. Everything is fake money; the numbers
*overstate* real performance (no partial fills, no market impact, estimated
slippage, ~15-min delayed data). Never connected to a broker.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Sequence

import pandas as pd
import streamlit as st

from src.core.config import settings
from src.core.storage import CashbookEntry, PaperTrade, Storage
from src.dashboard.components.data import get_store

_DISCLAIMER = (
    "⚠️ **Paper trading — simulated money only.** Slippage is estimated; intraday "
    "data is ~15 min delayed; results overstate real performance (no partial fills, "
    "market impact, or tax drag). Never connected to a broker."
)
_MIN_TRADES_FOR_STATS = 10


# --------------------------------------------------------------------------- #
# Pure helpers (unit-testable without Streamlit)
# --------------------------------------------------------------------------- #
def win_rate_breakdown(closed: Sequence[PaperTrade]) -> dict[str, dict[str, Any]]:
    """Group closed trades by exit reason → {reason: {n, wins, win_rate, avg_pnl}}."""
    buckets: dict[str, list[PaperTrade]] = defaultdict(list)
    for t in closed:
        buckets[t.exit_reason or "—"].append(t)
    out: dict[str, dict[str, Any]] = {}
    for reason, trades in buckets.items():
        wins = sum(1 for t in trades if t.pnl_dollars > 0)
        out[reason] = {
            "n": len(trades),
            "wins": wins,
            "win_rate": (wins / len(trades) * 100.0) if trades else 0.0,
            "avg_pnl": sum(t.pnl_dollars for t in trades) / len(trades) if trades else 0.0,
        }
    return out


def equity_curve_df(cashbook: Sequence[CashbookEntry]) -> pd.DataFrame:
    """NAV vs same-dollar VOO, indexed to 100 at the first snapshot."""
    if not cashbook:
        return pd.DataFrame()
    base_nav = cashbook[0].total_nav or 1.0
    base_voo = next((c.voo_nav for c in cashbook if c.voo_nav), None)
    rows = []
    for c in cashbook:
        row: dict[str, Any] = {"date": c.date, "Paper NAV": (c.total_nav / base_nav) * 100}
        if base_voo and c.voo_nav:
            row["VOO"] = (c.voo_nav / base_voo) * 100
        rows.append(row)
    return pd.DataFrame(rows).set_index("date")


# --------------------------------------------------------------------------- #
# Render
# --------------------------------------------------------------------------- #
def render(storage: Storage | None = None) -> None:
    storage = storage or get_store()
    st.header("🤖 Autonomous Paper Trades")
    st.warning(_DISCLAIMER)

    open_trades = storage.get_paper_trades(status="OPEN")
    pending = storage.get_paper_trades(status="PENDING")
    closed = storage.get_paper_trades(status="CLOSED")
    cashbook = storage.get_cashbook()

    if not (open_trades or pending or closed or cashbook):
        st.info(
            "No paper trades yet. Start the agent (`python -m src.agent`) — it queues "
            "entries at the daily close and fills them at the next open."
        )
        return

    budget = settings.paper_budget
    latest_nav = cashbook[-1].total_nav if cashbook else budget
    pnl = latest_nav - budget
    voo_nav = cashbook[-1].voo_nav if cashbook else budget
    alpha = latest_nav - voo_nav

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Paper NAV", f"${latest_nav:,.0f}", f"{pnl / budget * 100:+.1f}%")
    c2.metric("Budget", f"${budget:,.0f}")
    c3.metric("VOO (same $)", f"${voo_nav:,.0f}")
    c4.metric("Alpha vs VOO", f"${alpha:,.0f}", f"{alpha / budget * 100:+.1f}%")

    # --- equity curve ---
    curve = equity_curve_df(cashbook)
    if not curve.empty:
        st.subheader("Equity curve — paper NAV vs VOO (indexed to 100)")
        st.line_chart(curve)

    # --- open positions ---
    st.subheader(f"Open positions ({len(open_trades)})")
    if open_trades:
        rows = []
        for t in open_trades:
            rows.append(
                {
                    "Ticker": t.ticker,
                    "Entry": f"${t.entry_price:,.2f}",
                    "Shares": f"{t.shares:.2f}",
                    "Cost": f"${t.cost_basis:,.0f}",
                    "Stop": f"${t.stop_price:,.2f}",
                    "Target": f"${t.target_price:,.2f}",
                    "Queued exit": t.pending_exit_reason or "—",
                }
            )
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.caption("No open positions.")

    if pending:
        st.subheader(f"Pending entries ({len(pending)}) — fill at next open")
        st.dataframe(
            pd.DataFrame(
                [{"Ticker": t.ticker, "Planned $": f"${t.cost_basis:,.0f}",
                  "Stop": f"${t.stop_price:,.2f}", "Target": f"${t.target_price:,.2f}"}
                 for t in pending]
            ),
            use_container_width=True,
            hide_index=True,
        )

    # --- closed trades ---
    st.subheader(f"Closed trades ({len(closed)})")
    if closed:
        st.dataframe(
            pd.DataFrame(
                [{"Ticker": t.ticker, "Exit": t.exit_reason, "P&L $": round(t.pnl_dollars, 0),
                  "P&L %": round(t.pnl_pct, 1), "Days": t.holding_days,
                  "Exit price": round(t.exit_price, 2)}
                 for t in reversed(closed)]
            ),
            use_container_width=True,
            hide_index=True,
        )

        # --- decision snapshots ---
        with st.expander("Trade decision snapshots (why the agent acted)"):
            for t in reversed(closed[-20:]):
                snap = json.loads(t.signal_snapshot_json or "{}")
                st.markdown(
                    f"**{t.ticker}** · {t.exit_reason} · {t.pnl_pct:+.1f}% · "
                    f"composite {snap.get('composite', '—')} · grade {snap.get('grade', '—')}"
                )

    # --- win-rate breakdown ---
    st.subheader("Win-rate breakdown")
    if len(closed) < _MIN_TRADES_FOR_STATS:
        st.caption(f"Collecting data — need {_MIN_TRADES_FOR_STATS}+ closed trades "
                   f"(have {len(closed)}).")
    else:
        breakdown = win_rate_breakdown(closed)
        st.dataframe(
            pd.DataFrame(
                [{"Exit reason": k, "Trades": v["n"], "Win rate": f"{v['win_rate']:.0f}%",
                  "Avg P&L $": round(v["avg_pnl"], 0)}
                 for k, v in sorted(breakdown.items(), key=lambda kv: -kv[1]["n"])]
            ),
            use_container_width=True,
            hide_index=True,
        )
