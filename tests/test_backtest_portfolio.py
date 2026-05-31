"""Session 14: walk-forward portfolio backtest vs VOO.

Three concerns, isolated for testing:
  1. Pure performance-metric math (total return, CAGR, drawdown, Sharpe/Sortino,
     volatility) on a known NAV series.
  2. Turnover-cost application (basis points on weight change).
  3. The walk-forward replay has no lookahead — decisions at date T are identical
     whether or not future bars exist in the data.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from src.core import backtest_portfolio as bp
from tests.factories import make_ohlcv


# --- pure metric math ------------------------------------------------------ #
def test_total_return() -> None:
    assert bp.total_return([100.0, 110.0, 121.0]) == pytest.approx(0.21)


def test_total_return_empty_or_singleton_is_zero() -> None:
    assert bp.total_return([]) == 0.0
    assert bp.total_return([100.0]) == 0.0


def test_period_returns() -> None:
    rets = bp.period_returns([100.0, 110.0, 99.0])
    assert rets == pytest.approx([0.10, -0.10])


def test_max_drawdown_is_negative_peak_to_trough() -> None:
    # Peak 120 → trough 90 = -25%.
    assert bp.max_drawdown([100.0, 120.0, 90.0, 130.0]) == pytest.approx(-0.25)


def test_max_drawdown_zero_when_monotonic() -> None:
    assert bp.max_drawdown([100.0, 101.0, 102.0]) == 0.0


def test_cagr_doubles_in_one_year() -> None:
    dates = [date(2020, 1, 1), date(2021, 1, 1)]
    # ~1 year, value doubles → CAGR ≈ 100%.
    assert bp.cagr([100.0, 200.0], dates) == pytest.approx(1.0, abs=0.01)


def test_volatility_zero_for_constant_growth() -> None:
    # Identical returns → no dispersion (within floating-point noise).
    assert bp.annualized_volatility([0.1, 0.1, 0.1]) == pytest.approx(0.0, abs=1e-9)


def test_volatility_positive_for_varying_returns() -> None:
    assert bp.annualized_volatility([0.0, 0.2, -0.1]) > 0.0


def test_sharpe_positive_for_uptrend_zero_for_flat() -> None:
    up = bp.period_returns([100.0, 105.0, 110.0, 116.0])
    assert bp.sharpe(up) > 0.0
    assert bp.sharpe([0.0, 0.0, 0.0]) == 0.0  # no excess return, no risk → 0


def test_sortino_rewards_smaller_downside() -> None:
    # Both series have downside; the one with the *smaller* drawdown leg has the
    # higher Sortino (downside deviation is what's penalized, not total variance).
    mild = [0.06, -0.01, 0.05]
    harsh = [0.20, -0.10, 0.05]
    assert bp.sortino(mild) > bp.sortino(harsh)


def test_sortino_no_downside_is_infinite_guarded() -> None:
    # All-positive returns have no downside deviation → guard returns 0.0 sentinel.
    assert bp.sortino([0.01, 0.02, 0.03]) == 0.0


# --- turnover cost --------------------------------------------------------- #
def test_turnover_cost_basis_points() -> None:
    # Enter A at 50% of a $1,000 book → 0.5 turnover @ 15 bps = $0.75.
    cost = bp.turnover_cost(current={}, target={"A": 0.5}, nav=1000.0, bps=15.0)
    assert cost == pytest.approx(0.75)


def test_turnover_cost_counts_both_sides() -> None:
    # Sell B, buy C — each 0.5 turnover → total turnover 1.0.
    cost = bp.turnover_cost(
        current={"B": 0.5}, target={"C": 0.5}, nav=1000.0, bps=10.0
    )
    assert cost == pytest.approx(1.0)  # 1.0 turnover * 1000 * 10/10000


def test_turnover_cost_zero_when_unchanged() -> None:
    assert bp.turnover_cost({"A": 0.5}, {"A": 0.5}, nav=1000.0, bps=10.0) == 0.0


# --- walk-forward replay (no lookahead) ------------------------------------ #
def _ramp(start: float, step: float, n: int, start_date: str = "2021-01-01") -> pd.DataFrame:
    closes = [start + step * i for i in range(n)]
    return make_ohlcv(closes, start=start_date)


def _price_map() -> dict[str, pd.DataFrame]:
    # Three names with different slopes so ranking is non-trivial.
    return {
        "AAA": _ramp(100.0, 1.0, 120),
        "BBB": _ramp(100.0, 0.5, 120),
        "CCC": _ramp(100.0, 0.2, 120),
    }


def _benchmark() -> pd.DataFrame:
    return _ramp(400.0, 0.4, 120)


def test_backtest_runs_and_reports_metrics() -> None:
    result = bp.run_backtest(_price_map(), _benchmark(), cadence="weekly")
    assert len(result.nav) == len(result.dates)
    assert result.nav[0] == pytest.approx(result.start_balance)
    # In a clean uptrend the paper book should end above its start.
    assert result.nav[-1] > result.nav[0]
    # Metric containers are populated.
    assert result.strategy.total_return != 0.0
    assert result.benchmark.total_return != 0.0
    assert 0.0 <= result.pct_months_beating <= 100.0


def test_backtest_has_no_lookahead() -> None:
    pmap = _price_map()
    bench = _benchmark()
    full = bp.run_backtest(pmap, bench, cadence="weekly")

    # Truncate every frame to a cutoff that is itself a rebalance date.
    cutoff = full.rebalance_dates[len(full.rebalance_dates) // 2]
    trunc_map = {t: df[df.index.date <= cutoff] for t, df in pmap.items()}
    trunc_bench = bench[bench.index.date <= cutoff]
    truncated = bp.run_backtest(trunc_map, trunc_bench, cadence="weekly")

    # Every rebalance decision up to the cutoff must be identical — future bars
    # that exist in `full` but not `truncated` cannot have influenced them.
    for d in truncated.rebalance_dates:
        assert full.targets_at(d) == truncated.targets_at(d), f"lookahead at {d}"


def test_backtest_applies_costs_reducing_nav() -> None:
    pmap = _price_map()
    bench = _benchmark()
    free = bp.run_backtest(pmap, bench, cadence="weekly", cost_bps=0.0, slippage_bps=0.0)
    costly = bp.run_backtest(pmap, bench, cadence="weekly", cost_bps=50.0, slippage_bps=50.0)
    # Costs are a drag: the costed run ends with a lower NAV and positive cost drag.
    assert costly.nav[-1] < free.nav[-1]
    assert costly.cost_drag > 0.0
    assert free.cost_drag == pytest.approx(0.0)


def test_backtest_window_trims_to_years() -> None:
    # 800 daily bars (~3.2y); a 1-year window keeps far fewer dates.
    long_map = {"AAA": _ramp(100.0, 0.1, 800)}
    long_bench = _ramp(400.0, 0.1, 800)
    result = bp.run_backtest(long_map, long_bench, cadence="weekly", years=1)
    span_days = (result.dates[-1] - result.dates[0]).days
    assert span_days <= 400  # ~1 year, not the full ~3.2y history


def test_empty_inputs_return_empty_result() -> None:
    result = bp.run_backtest({}, pd.DataFrame())
    assert result.nav == []
    assert result.rebalance_dates == []


# --- jobs entry point (fetch + delegate) ----------------------------------- #
def test_run_portfolio_backtest_uses_injected_fetcher() -> None:
    from src.agent import jobs

    frames = {**_price_map(), "VOO": _benchmark()}

    def fetcher(ticker: str, bars: int) -> pd.DataFrame:
        return frames.get(ticker, pd.DataFrame())

    result = jobs.run_portfolio_backtest(
        tickers=["AAA", "BBB", "CCC"], fetcher=fetcher, cadence="weekly"
    )
    assert result.nav  # ran end-to-end against the fetched frames
    assert result.benchmark_nav
