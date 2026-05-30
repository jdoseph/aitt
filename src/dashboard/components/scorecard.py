"""Renderers for the setup quality scorecard + breadth/leadership header."""

from __future__ import annotations

from typing import Any

import streamlit as st

from src.core.market import MarketContext
from src.core.scorecard import CHECK_TITLES
from src.core.watchlist import Watchlist

_GLYPH = {"pass": "✅", "warn": "⚠️", "fail": "❌", "na": "•"}
ACTION_COLOR = {
    "HIGH-QUALITY": "#16a34a",
    "DECENT": "#65a30d",
    "MARGINAL": "#d97706",
    "AVOID": "#dc2626",
}
ACTION_RANK = {"HIGH-QUALITY": 3, "DECENT": 2, "MARGINAL": 1, "AVOID": 0}


def action_badge_html(action: str | None) -> str:
    """An inline colored pill for an action grade (empty string if ungraded)."""
    if not action:
        return ""
    color = ACTION_COLOR.get(action, "#6b7280")
    return (
        f"<span style='background:{color};color:white;padding:2px 8px;"
        f"border-radius:10px;font-size:0.8em;font-weight:600'>{action}</span>"
    )


def render_scorecard(summary: dict[str, Any]) -> None:
    """Render a stored scorecard summary (the dict from Scorecard.to_summary)."""
    action = summary.get("action")
    st.markdown("**Setup quality** &nbsp; " + action_badge_html(action), unsafe_allow_html=True)
    for check in summary.get("checks", []):
        glyph = _GLYPH.get(check.get("status", ""), "")
        title = CHECK_TITLES.get(check.get("name", ""), check.get("name", ""))
        st.write(f"{glyph} **{title}** — {check.get('value', '')}")


def render_market_header(ctx: MarketContext, watchlist: Watchlist) -> None:
    """Breadth + leading-layers summary for the top of the Overview page."""
    b = ctx.breadth
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Bullish", b.bullish)
    c2.metric("Neutral", b.neutral)
    c3.metric("Bearish", b.bearish)
    c4.metric("Tape", "Healthy ✅" if b.healthy else "Cautious ⚠️")
    if ctx.leading_layers:
        titles = [watchlist.layer_title(k) for k, _ in ctx.leadership[: len(ctx.leading_layers)]]
        st.caption("Leading layers: " + " · ".join(titles))
