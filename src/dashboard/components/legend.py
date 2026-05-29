"""Reusable legend explaining the chart's visual elements and the signal vocabulary."""

from __future__ import annotations

import streamlit as st

# Note: the colored squares below match the line/shape colors used in charts.py
# (EMA 9 green, EMA 21 orange, EMA 50 blue, ATH purple) and theme.py status dots.
_CHART_ELEMENTS_MD = """
**Chart elements**

- 🟩 **green / 🟥 red candles** — up day (close ≥ open) / down day; the thin wicks are the intraday high & low.
- 🟩 **EMA 9** — 9-day exponential moving average (short-term trend).
- 🟧 **EMA 21** — 21-day EMA, the primary pullback reference (a touch here is the main EMA alert).
- 🟦 **EMA 50** — 50-day EMA, the longer-term trend filter (price above it = uptrend intact).
- 🟪 **purple dotted line** — all-time high (ATH); the ATH-dip % is measured from here.
- 🟦 **blue shaded box** — the active consolidation range (base high↔low) over the days it has held.
- **bottom bars** — daily volume (green/red by day); the **gray line** is the 20-day average volume. Breakouts must clear this to count.
- 🔻 **yellow triangles** — where an alert fired in the past (hover for the status + stars).
"""

_SIGNALS_MD = """
**Signal vocabulary**

- **EMA**: `AT_21_EMA` / `AT_9_EMA` = touching that EMA (entry) · `APPROACHING_*` = within range above ·
  `EXTENDED` = >8% above the 21 EMA (too far) · `BELOW_21_EMA` = broken below · `NEUTRAL` = in-trend, nothing to do.
- **ATH**: `AT_ATH` (≤1% off) · `MINOR_PULLBACK` (1–5%) · `ENTRY_ZONE` (5–10%, best risk/reward) ·
  `DEEP_PULLBACK` (10–20%) · `CORRECTION` (>20%).
- **FLAG**: `CONSOLIDATING` (tight base) · `BREAKOUT` / `BREAKDOWN` (clears the range on volume) · `NO_PATTERN`.
- **IPO** (only <60 trading days old): `IPO_FRESH` · `IPO_BASING` · `IPO_BREAKOUT` · `IPO_FAILED` (−25% from IPO high).

**Confidence** ⭐ signal only · ⭐⭐ + moderate pattern (hammer / three white soldiers / piercing / doji at support) ·
⭐⭐⭐ + strong pattern (bullish engulfing / morning star).

**Status dots** 🟢 at/approaching entry · 🟡 approaching · 🟠 deep dip · 🔵 neutral / basing · 🔴 broken / avoid · ⚪ not actionable.
"""


def render_chart_legend(expanded: bool = False) -> None:
    """Render an expandable legend describing the chart and signal terms."""
    with st.expander("📖 Legend — what am I looking at?", expanded=expanded):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown(_CHART_ELEMENTS_MD)
        with col2:
            st.markdown(_SIGNALS_MD)
