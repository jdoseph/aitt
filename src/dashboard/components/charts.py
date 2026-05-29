"""Plotly candlestick chart builder: EMAs, ATH, consolidation shading,
volume + 20-day average, and historical alert markers."""

from __future__ import annotations

import json
from datetime import date as Date

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from src.core.indicators import add_emas, all_time_high, average_volume
from src.core.storage import SignalRecord

_EMA_COLORS = {"ema_9": "#22c55e", "ema_21": "#f59e0b", "ema_50": "#3b82f6"}


def build_price_chart(
    ticker: str,
    df: pd.DataFrame,
    signals: dict[str, SignalRecord] | None = None,
    alerts: list[tuple[Date, str, int]] | None = None,
    last_n: int = 90,
) -> go.Figure:
    """Return a 2-row figure (price+overlays, volume) for ``ticker``."""
    full = add_emas(df)
    view = full.tail(last_n)

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.76, 0.24],
    )

    # --- price candles ---
    fig.add_trace(
        go.Candlestick(
            x=view.index,
            open=view["open"],
            high=view["high"],
            low=view["low"],
            close=view["close"],
            name=ticker,
            increasing_line_color="#26a69a",
            decreasing_line_color="#ef5350",
        ),
        row=1,
        col=1,
    )

    # --- EMA overlays ---
    for col, color in _EMA_COLORS.items():
        if col in view:
            fig.add_trace(
                go.Scatter(
                    x=view.index, y=view[col], name=col.replace("_", " ").upper(),
                    line=dict(color=color, width=1.2),
                ),
                row=1,
                col=1,
            )

    # --- ATH line ---
    ath, _ = all_time_high(full)
    fig.add_hline(
        y=ath, line=dict(color="#9333ea", width=1, dash="dot"),
        annotation_text=f"ATH {ath:.2f}", annotation_position="top left", row=1, col=1,
    )

    # --- consolidation range shading (from the FLAG signal, if active) ---
    cons = (signals or {}).get("consolidation_breakout")
    if cons and cons.status in ("CONSOLIDATING", "BREAKOUT", "BREAKDOWN"):
        d = json.loads(cons.details or "{}")
        rh, rl, days = d.get("range_high"), d.get("range_low"), d.get("days_in_range")
        if rh and rl and days:
            start_idx = max(0, len(view) - int(days) - 1)
            fig.add_shape(
                type="rect",
                x0=view.index[start_idx], x1=view.index[-1],
                y0=rl, y1=rh,
                fillcolor="rgba(96,165,250,0.12)", line=dict(width=0),
                row=1, col=1,
            )

    # --- alert markers ---
    if alerts:
        view_dates = {d.date(): d for d in view.index}
        mx, my, mt = [], [], []
        for adate, status, conf in alerts:
            ts = view_dates.get(adate)
            if ts is None:
                continue
            mx.append(ts)
            my.append(float(view.loc[ts, "high"]) * 1.02)
            mt.append(f"{status} {'⭐' * conf}")
        if mx:
            fig.add_trace(
                go.Scatter(
                    x=mx, y=my, mode="markers", name="alerts",
                    marker=dict(symbol="triangle-down", size=11, color="#fbbf24"),
                    text=mt, hoverinfo="text",
                ),
                row=1, col=1,
            )

    # --- volume + 20-day average ---
    vol_avg = average_volume(full).tail(last_n)
    colors = ["#26a69a" if c >= o else "#ef5350" for o, c in zip(view["open"], view["close"])]
    fig.add_trace(
        go.Bar(x=view.index, y=view["volume"], name="volume", marker_color=colors, opacity=0.5),
        row=2, col=1,
    )
    fig.add_trace(
        go.Scatter(x=vol_avg.index, y=vol_avg, name="vol avg", line=dict(color="#94a3b8", width=1)),
        row=2, col=1,
    )

    fig.update_layout(
        height=620,
        margin=dict(l=10, r=10, t=30, b=10),
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0),
        hovermode="x unified",
    )
    fig.update_yaxes(title_text="Price", row=1, col=1)
    fig.update_yaxes(title_text="Vol", row=2, col=1)
    return fig
