"""Walk-forward portfolio backtest vs VOO (Session 14) — the verdict.

Replays the Session 13 portfolio mechanism over years of real daily bars and
measures the paper book against the benchmark (VOO) net of estimated costs. This
is the *only* thing that answers "does this beat the S&P 500?" — and the honest
read in CLAUDE.md applies: if it doesn't beat VOO on a risk-adjusted basis net of
costs through a real drawdown, that's the answer.

**Faithful where it counts, honest about its limits.** The replay reuses the real
machinery — the regime read, the :mod:`exposure` dial (with hysteresis), the
:mod:`sizing` engine (conviction weights + concentration caps + RS rotation), and
each name's 50-EMA eligibility. What it does *not* replay is the network scorecard
(earnings/news/revised fundamentals would both leak lookahead and be
irreproducible). Instead the universe is ranked each rebalance by a **price-only
score proxy** (trailing return by default), injected as ``scorer``. So this
validates the *exposure + concentration + rotation* edge — which the spec names as
the real source of alpha — not entry-signal precision.

No lookahead: every decision at date *T* slices price history to ``<= T`` only.
Pure given its inputs (prices + an injected scorer). Paper-only.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date as Date

import pandas as pd

from src.core import exposure as exposure_mod
from src.core import regime as regime_mod
from src.core import sizing as sizing_mod
from src.core.benchmarks import return_pct
from src.core.config import settings
from src.core.indicators import compute_metrics
from src.core.portfolio import PaperPortfolio
from src.core.sizing import Candidate

# --------------------------------------------------------------------------- #
# Pure performance metrics
# --------------------------------------------------------------------------- #
def period_returns(nav: Sequence[float]) -> list[float]:
    """Simple period-over-period returns of a NAV series."""
    out: list[float] = []
    for prev, cur in zip(nav, nav[1:]):
        out.append(cur / prev - 1.0 if prev else 0.0)
    return out


def total_return(nav: Sequence[float]) -> float:
    """End/start - 1 over the whole series (0 for empty/singleton)."""
    if len(nav) < 2 or nav[0] == 0:
        return 0.0
    return nav[-1] / nav[0] - 1.0


def cagr(nav: Sequence[float], dates: Sequence[Date]) -> float:
    """Compound annual growth rate, annualized by the actual calendar span."""
    if len(nav) < 2 or nav[0] <= 0 or nav[-1] <= 0:
        return 0.0
    years = (dates[-1] - dates[0]).days / 365.25
    if years <= 0:
        return 0.0
    return (nav[-1] / nav[0]) ** (1.0 / years) - 1.0


def max_drawdown(nav: Sequence[float]) -> float:
    """Largest peak-to-trough decline as a negative fraction (0.0 if monotonic up)."""
    worst = 0.0
    peak = nav[0] if nav else 0.0
    for v in nav:
        peak = max(peak, v)
        if peak > 0:
            worst = min(worst, v / peak - 1.0)
    return worst


def _std(values: Sequence[float]) -> float:
    """Sample standard deviation (ddof=1); 0.0 for fewer than two points."""
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    return math.sqrt(var)


def annualized_volatility(returns: Sequence[float], periods_per_year: int | None = None) -> float:
    ppy = periods_per_year or settings.trading_days_per_year
    return _std(returns) * math.sqrt(ppy)


def sharpe(returns: Sequence[float], periods_per_year: int | None = None, rf: float = 0.0) -> float:
    """Annualized Sharpe ratio (0.0 when there is no return dispersion)."""
    if not returns:
        return 0.0
    ppy = periods_per_year or settings.trading_days_per_year
    excess = [r - rf / ppy for r in returns]
    sd = _std(excess)
    if sd == 0:
        return 0.0
    mean = sum(excess) / len(excess)
    return mean / sd * math.sqrt(ppy)


def sortino(returns: Sequence[float], periods_per_year: int | None = None, rf: float = 0.0) -> float:
    """Annualized Sortino ratio (downside deviation; 0.0 when no downside)."""
    if not returns:
        return 0.0
    ppy = periods_per_year or settings.trading_days_per_year
    excess = [r - rf / ppy for r in returns]
    downside = [min(0.0, r) for r in excess]
    dd = math.sqrt(sum(d * d for d in downside) / len(downside))
    if dd == 0:
        return 0.0
    mean = sum(excess) / len(excess)
    return mean / dd * math.sqrt(ppy)


def turnover_cost(
    current: Mapping[str, float], target: Mapping[str, float], nav: float, bps: float
) -> float:
    """Cost of moving from ``current`` to ``target`` weights: turnover × bps × NAV."""
    names = set(current) | set(target)
    turnover = sum(abs(target.get(t, 0.0) - current.get(t, 0.0)) for t in names)
    return turnover * nav * bps / 10_000.0


# --------------------------------------------------------------------------- #
# Result container
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class PerfStats:
    total_return: float = 0.0
    cagr: float = 0.0
    max_drawdown: float = 0.0  # negative fraction
    sharpe: float = 0.0
    sortino: float = 0.0
    volatility: float = 0.0  # annualized


@dataclass
class BacktestResult:
    dates: list[Date] = field(default_factory=list)
    nav: list[float] = field(default_factory=list)  # paper book NAV (after costs)
    benchmark_nav: list[float] = field(default_factory=list)  # VOO, indexed to start_balance
    exposure_series: list[float] = field(default_factory=list)  # 0-1 invested fraction per day
    strategy: PerfStats = field(default_factory=PerfStats)
    benchmark: PerfStats = field(default_factory=PerfStats)
    pct_months_beating: float = 0.0
    longest_underperformance_months: int = 0
    total_turnover: float = 0.0  # summed weight change across rebalances
    cost_drag: float = 0.0  # total cost paid / start balance
    regime_mean_daily_return: dict[str, float] = field(default_factory=dict)
    rebalance_dates: list[Date] = field(default_factory=list)
    start_balance: float = 0.0
    _targets: dict[Date, dict[str, float]] = field(default_factory=dict)

    def targets_at(self, d: Date) -> dict[str, float]:
        """Target weights chosen on rebalance date ``d`` (empty if not a rebalance)."""
        return self._targets.get(d, {})


# --------------------------------------------------------------------------- #
# Walk-forward replay
# --------------------------------------------------------------------------- #
_CADENCE_DAYS = {"daily": 1, "weekly": 7, "monthly": 28}


def _default_scorer(df: pd.DataFrame) -> float:
    """Price-only rank proxy: trailing return over the RS lookback (0 if too thin)."""
    r = return_pct(df, settings.rs_lookback)
    return 0.0 if r is None else r


def _aligned_closes(
    price_map: Mapping[str, pd.DataFrame], calendar: pd.DatetimeIndex
) -> pd.DataFrame:
    """Closes for every ticker on the benchmark calendar, forward-filled."""
    cols = {}
    for ticker, df in price_map.items():
        s = df["close"].copy()
        s.index = pd.DatetimeIndex(s.index)
        cols[ticker] = s.reindex(calendar, method="ffill")
    return pd.DataFrame(cols, index=calendar)


def _build_candidates(
    price_map: Mapping[str, pd.DataFrame],
    as_of: pd.Timestamp,
    scorer: Callable[[pd.DataFrame], float],
    min_bars: int,
) -> list[Candidate]:
    """Rank the universe by the price-only score using only bars on/before ``as_of``."""
    scored: list[tuple[str, float, bool]] = []
    for ticker, df in price_map.items():
        hist = df[df.index <= as_of]
        if len(hist) < min_bars:
            continue
        m = compute_metrics(hist)
        above_50 = True if m.above_50_ema is None else m.above_50_ema
        scored.append((ticker, scorer(hist), above_50))
    scored.sort(key=lambda x: x[1], reverse=True)
    return [
        Candidate(ticker=t, score=s, rank=i + 1, grade="DECENT", above_50_ema=a50)
        for i, (t, s, a50) in enumerate(scored)
    ]


def _regime_label_at(
    regime_symbols: Mapping[str, pd.DataFrame], as_of: pd.Timestamp
) -> str:
    sliced = {sym: df[df.index <= as_of] for sym, df in regime_symbols.items()}
    return regime_mod.market_regime(sliced).label


def run_backtest(
    price_map: Mapping[str, pd.DataFrame],
    benchmark_df: pd.DataFrame,
    *,
    regime_symbols: Mapping[str, pd.DataFrame] | None = None,
    scorer: Callable[[pd.DataFrame], float] | None = None,
    start_balance: float | None = None,
    cadence: str | None = None,
    cost_bps: float | None = None,
    slippage_bps: float | None = None,
    years: int | None = None,
    min_bars: int = 50,
) -> BacktestResult:
    """Replay the portfolio mechanism over history and score it against the benchmark.

    Args:
        price_map: ticker → daily OHLCV (full available history).
        benchmark_df: the benchmark's daily OHLCV (VOO); defines the trading calendar.
        regime_symbols: index frames for the regime read (defaults to the benchmark).
        scorer: price-only ranking score per ticker (defaults to trailing return).
        years: history window to keep (defaults to ``settings.backtest_years``).
    """
    if not price_map or benchmark_df is None or benchmark_df.empty:
        return BacktestResult()

    scorer = scorer or _default_scorer
    start_balance = start_balance if start_balance is not None else settings.paper_start_balance
    cadence = cadence or settings.rebalance_cadence
    cost_bps = settings.cost_per_trade_bps if cost_bps is None else cost_bps
    slippage_bps = settings.slippage_bps if slippage_bps is None else slippage_bps
    years = years or settings.backtest_years
    total_bps = cost_bps + slippage_bps
    regime_symbols = regime_symbols or {settings.portfolio_benchmark: benchmark_df}

    # Trading calendar = benchmark dates, trimmed to the requested window.
    calendar = pd.DatetimeIndex(benchmark_df.index)
    cutoff = calendar[-1] - pd.Timedelta(days=int(round(years * 365.25)))
    calendar = calendar[calendar >= cutoff]
    if len(calendar) < 2:
        return BacktestResult()

    closes = _aligned_closes(price_map, calendar)
    bench_close = benchmark_df["close"].reindex(calendar, method="ffill")
    spacing = _CADENCE_DAYS.get(cadence, 7)

    portfolio = PaperPortfolio.empty(start_balance)
    regime_history: list[str] = []
    result = BacktestResult(start_balance=start_balance)
    bench_units = start_balance / float(bench_close.iloc[0])  # VOO shares for an equal start

    last_rebalance: pd.Timestamp | None = None
    exposure = 0.0
    for ts in calendar:
        prices = {t: float(v) for t, v in closes.loc[ts].items() if pd.notna(v)}

        due = last_rebalance is None or (ts - last_rebalance).days >= spacing
        if due:
            label = _regime_label_at(regime_symbols, ts)
            regime_history.append(label)
            exposure = exposure_mod.target_exposure(regime_history).exposure

            candidates = _build_candidates(price_map, ts, scorer, min_bars)
            held = portfolio.current_weights(prices)
            plan = sizing_mod.target_weights(candidates, exposure, held)

            nav_before = portfolio.nav(prices)
            cost = turnover_cost(held, plan.target_weights, nav_before, total_bps)
            portfolio.apply_targets(plan.target_weights, prices)
            portfolio.cash -= cost

            d = ts.date()
            result.rebalance_dates.append(d)
            result._targets[d] = dict(plan.target_weights)
            result.total_turnover += sum(
                abs(plan.target_weights.get(t, 0.0) - held.get(t, 0.0))
                for t in set(plan.target_weights) | set(held)
            )
            result.cost_drag += cost / start_balance
            last_rebalance = ts

        result.dates.append(ts.date())
        result.nav.append(portfolio.nav(prices))
        result.benchmark_nav.append(bench_units * float(bench_close.loc[ts]))
        result.exposure_series.append(exposure)

    _finalize_metrics(result, calendar, regime_symbols)
    return result


def _finalize_metrics(
    result: BacktestResult,
    calendar: pd.DatetimeIndex,
    regime_symbols: Mapping[str, pd.DataFrame],
) -> None:
    """Compute the summary stats vs the benchmark once the NAV series is built."""
    result.strategy = _perf_stats(result.nav, result.dates)
    result.benchmark = _perf_stats(result.benchmark_nav, result.dates)
    result.pct_months_beating, result.longest_underperformance_months = _monthly_comparison(
        result.dates, result.nav, result.benchmark_nav
    )
    result.regime_mean_daily_return = _regime_breakdown(
        calendar, result.nav, regime_symbols
    )


def _perf_stats(nav: Sequence[float], dates: Sequence[Date]) -> PerfStats:
    rets = period_returns(nav)
    return PerfStats(
        total_return=total_return(nav),
        cagr=cagr(nav, dates),
        max_drawdown=max_drawdown(nav),
        sharpe=sharpe(rets),
        sortino=sortino(rets),
        volatility=annualized_volatility(rets),
    )


def _monthly_comparison(
    dates: Sequence[Date], nav: Sequence[float], bench: Sequence[float]
) -> tuple[float, int]:
    """% of months the strategy beat the benchmark + longest losing streak (months)."""
    if not dates:
        return 0.0, 0
    s = pd.DataFrame({"nav": nav, "bench": bench}, index=pd.DatetimeIndex(dates))
    monthly = s.resample("ME").last()
    nav_ret = monthly["nav"].pct_change().dropna()
    bench_ret = monthly["bench"].pct_change().dropna()
    if nav_ret.empty:
        return 0.0, 0
    beat = nav_ret > bench_ret
    pct = float(beat.mean() * 100.0)
    longest = streak = 0
    for won in beat:
        streak = 0 if won else streak + 1
        longest = max(longest, streak)
    return pct, longest


def _regime_breakdown(
    calendar: pd.DatetimeIndex,
    nav: Sequence[float],
    regime_symbols: Mapping[str, pd.DataFrame],
) -> dict[str, float]:
    """Mean daily strategy return grouped by that day's regime label."""
    rets = period_returns(nav)
    buckets: dict[str, list[float]] = {}
    # rets[i] is the return earned on calendar[i+1].
    for ts, r in zip(calendar[1:], rets):
        label = _regime_label_at(regime_symbols, ts)
        buckets.setdefault(label, []).append(r)
    return {label: sum(v) / len(v) for label, v in buckets.items() if v}
