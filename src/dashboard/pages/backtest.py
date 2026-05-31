"""Backtest page — walk-forward paper book vs VOO, net of costs (Session 14).

The verdict tab. Replays the full Session 13 mechanism (regime dial → conviction
sizing → RS rotation) over years of real bars and charts the paper NAV against
VOO, with the risk-adjusted metrics that decide whether the edge is real.

**Honest read (from CLAUDE.md):** if the strategy doesn't beat VOO on a
risk-adjusted basis (Sharpe) net of costs through a real drawdown, that's the
answer — a smoother ride at lower return is legitimate; higher return with far
deeper drawdowns is not a win. The replay ranks names by a price-only proxy, so
it validates the *exposure + concentration + rotation* edge, not entry precision.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.core.backtest_portfolio import BacktestResult, PerfStats
from src.core.config import settings


def render() -> None:
    st.header("📉 Backtest vs VOO (the verdict)")
    st.caption(
        "Walk-forward replay of the paper portfolio, net of estimated costs. "
        "Ranks by a price-only proxy — validates exposure/concentration/rotation, "
        "not entry-signal precision. Nothing here is investment advice."
    )

    c1, c2, c3 = st.columns(3)
    years = c1.number_input("Years", 1, 10, settings.backtest_years)
    cadence = c2.selectbox(
        "Rebalance", ["weekly", "monthly", "daily"],
        index=["weekly", "monthly", "daily"].index(settings.rebalance_cadence),
    )
    run = c3.button("▶ Run backtest", type="primary")

    if run:
        from src.agent import jobs

        with st.spinner(f"Fetching ~{years}y of history and replaying… (network-heavy)"):
            try:
                fresh = jobs.run_portfolio_backtest(cadence=str(cadence), years=int(years))
            except Exception as exc:  # noqa: BLE001 - surface the failure, don't crash the page
                st.error(f"Backtest failed: {exc}")
                return
        st.session_state["backtest_result"] = fresh

    result: BacktestResult | None = st.session_state.get("backtest_result")
    if result is None:
        st.info("Press **Run backtest** to replay the strategy against VOO.")
        return
    if not result.nav:
        st.warning("No data returned — the benchmark or price history was unavailable.")
        return

    _render_result(result)


def _verdict(result: BacktestResult) -> tuple[str, str]:
    """A blunt, risk-adjusted call: Sharpe is the arbiter (per the spec)."""
    s, b = result.strategy, result.benchmark
    if s.sharpe > b.sharpe and s.total_return >= b.total_return:
        return "🟢", "Beat VOO on return AND risk-adjusted (Sharpe) — net of costs."
    if s.sharpe > b.sharpe:
        return "🟡", "Smoother ride (higher Sharpe) at a lower return — a legitimate outcome."
    if s.total_return > b.total_return:
        return "🟡", "Higher return but worse Sharpe — more return for more risk; not a clear win."
    return "🔴", "Did not beat VOO on return or risk-adjusted basis. Do not deploy capital."


def _render_result(result: BacktestResult) -> None:
    badge, verdict = _verdict(result)
    st.markdown(f"### {badge} {verdict}")

    # --- equity curve (indexed to 100) ---
    index = pd.to_datetime(pd.Series(result.dates))
    eq = pd.DataFrame(
        {"Strategy": result.nav, "VOO": result.benchmark_nav},
        index=index,
    )
    eq = eq / eq.iloc[0] * 100.0
    st.subheader("Equity curve (indexed to 100)")
    st.line_chart(eq)

    # --- drawdown ---
    st.subheader("Drawdown")
    dd = pd.DataFrame(
        {"Strategy": _drawdown_series(result.nav), "VOO": _drawdown_series(result.benchmark_nav)},
        index=index,
    )
    st.area_chart(dd)

    # --- metrics table ---
    st.subheader("Performance vs VOO (net of costs)")
    st.dataframe(_metrics_table(result.strategy, result.benchmark), hide_index=True,
                 use_container_width=True)

    c1, c2, c3 = st.columns(3)
    c1.metric("% months beating VOO", f"{result.pct_months_beating:.0f}%")
    c2.metric("Longest underperformance", f"{result.longest_underperformance_months} mo")
    c3.metric("Cost drag", f"{result.cost_drag * 100:.1f}%", f"turnover {result.total_turnover:.1f}x")

    # --- regime-conditional breakdown ---
    if result.regime_mean_daily_return:
        st.subheader("Mean daily return by regime")
        st.caption("Does the exposure dial add value, or just cut return? (annualized in parens)")
        ppy = settings.trading_days_per_year
        rows = [
            {
                "Regime": label,
                "Mean daily %": f"{r * 100:.3f}%",
                "Annualized %": f"{((1 + r) ** ppy - 1) * 100:.1f}%",
            }
            for label, r in result.regime_mean_daily_return.items()
        ]
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


def _drawdown_series(nav: list[float]) -> list[float]:
    out: list[float] = []
    peak = nav[0] if nav else 0.0
    for v in nav:
        peak = max(peak, v)
        out.append((v / peak - 1.0) * 100.0 if peak > 0 else 0.0)
    return out


def _metrics_table(strat: PerfStats, bench: PerfStats) -> pd.DataFrame:
    def row(label: str, a: float, b: float, pct: bool = True) -> dict[str, str]:
        def fmt(x: float) -> str:
            return f"{x * 100:.1f}%" if pct else f"{x:.2f}"

        return {"Metric": label, "Strategy": fmt(a), "VOO": fmt(b)}

    return pd.DataFrame(
        [
            row("Total return", strat.total_return, bench.total_return),
            row("CAGR", strat.cagr, bench.cagr),
            row("Max drawdown", strat.max_drawdown, bench.max_drawdown),
            row("Volatility (ann.)", strat.volatility, bench.volatility),
            row("Sharpe", strat.sharpe, bench.sharpe, pct=False),
            row("Sortino", strat.sortino, bench.sortino, pct=False),
        ]
    )
