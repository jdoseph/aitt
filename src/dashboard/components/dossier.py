"""Renderer for the trade due-diligence dossier (Session 9)."""

from __future__ import annotations

from typing import Any

import streamlit as st

from src.dashboard.components.scorecard import action_badge_html


def render_dossier(summary: dict[str, Any]) -> None:
    """Render a stored dossier summary (the dict from Dossier.to_summary)."""
    grade = summary.get("grade")
    st.markdown(
        "**Due-diligence dossier** &nbsp; " + action_badge_html(grade), unsafe_allow_html=True
    )

    buy = summary.get("reasons_to_buy") or []
    nobuy = summary.get("reasons_not_to_buy") or []
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**✅ Reasons to BUY**")
        if buy:
            for r in buy:
                st.markdown(f"- {r}")
        else:
            st.caption("None registered.")
    with c2:
        st.markdown("**⛔ Reasons NOT to buy**")
        for r in nobuy:
            st.markdown(f"- {r}")

    sb, sbear = summary.get("strongest_bull"), summary.get("strongest_bear")
    if sb or sbear:
        st.caption(f"Strongest bull: **{sb or '—'}**  ·  Strongest bear: **{sbear or '—'}**")

    # Context line.
    st.markdown(
        f"**Confluence:** {summary.get('confluence', 0)}/4 "
        f"({summary.get('confluence_detail') or '—'})  \n"
        f"**Extension:** {summary.get('extension', 'n/a')}  \n"
        f"**Trend:** {summary.get('trend_alignment', 'n/a')}  \n"
        f"**Market regime:** {summary.get('market_regime', 'n/a')}"
    )

    plan = summary.get("trade_plan") or {}
    if plan:
        target = plan.get("target")
        rr = plan.get("risk_reward")
        targets = " / ".join(str(p) for p in plan.get("profit_targets", []))
        st.markdown(
            "**Trade plan** _(informational — never auto-executed)_  \n"
            f"Entry ~{plan.get('entry')} · Stop {plan.get('stop')} "
            f"· Target {target if target is not None else '—'} "
            f"· R:R {rr if rr is not None else '—'}  \n"
            f"Size: **{plan.get('sizing_tier', '—')}** · "
            f"Take profits: {targets or '—'}  \n"
            f"Invalidation: _{plan.get('invalidation', '—')}_"
        )

    manual = summary.get("manual_catalyst_checks") or []
    if manual:
        with st.expander("Manual catalyst checks (no free feed)"):
            for m in manual:
                st.markdown(f"- {m}")
