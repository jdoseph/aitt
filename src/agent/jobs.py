"""Agent jobs: refresh prices, evaluate signals, fire alerts, and the full cycle.

These are plain functions so they can be called from the scheduler, the CLI
(``--once``), or tests. Each is defensive: a single failing ticker is logged and
skipped, never aborting the cycle.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date as Date
from datetime import datetime
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
from loguru import logger

from src.agent import notify
from src.core import backtest, backtest_portfolio, benchmarks, earnings, execution, news
from src.core.backtest_portfolio import BacktestResult
from src.core.config import settings
from src.core.data import DataFetchError, fetch_many, fetch_prices
from src.core.execution import BUY, SELL, Side, check_gap, slippage_bps
from src.core.options import chain as option_chain
from src.core.options import vol as option_vol
from src.core.options.contracts import OptionContract, select_contract
from src.core.options.option_trades import OptionBook, evaluate_exit, mark_premium
from src.core.options.pricing import entry_premium
from src.core.paper_trades import PaperBook
from src.core.signals import CycleResult, SignalEngine
from src.core.storage import CashbookEntry, OptionTrade, PaperTrade, Storage
from src.core.watchlist import load_watchlist

# A daily exit's priority order (lower index = higher priority).
_DAILY_EXIT_PRIORITY = ["EXIT_EMA", "EXIT_REGIME", "EXIT_ROTATION", "EXIT_TIME", "EXIT_QUALITY"]
_GRADE_ORDER = ["AVOID", "MARGINAL", "DECENT", "HIGH-QUALITY"]

# Default slippage estimator: liquidity tier only (no live market-cap / ADV here).
SlippageFn = Callable[[str, Side, float], float]

# Session 16 — injectable providers for the options jobs (offline in tests).
ChainProvider = Callable[[str, int, Date], "dict[str, Any] | None"]
UnderlyingDateProvider = Callable[[str, Date], "float | None"]
UnderlyingProvider = Callable[[str], "float | None"]
PriceFrameProvider = Callable[[str], pd.DataFrame]


def _default_slippage(ticker: str, side: Side, position_dollars: float) -> float:
    return slippage_bps(ticker, side)


def _grade_ok(grade: str, minimum: str) -> bool:
    try:
        return _GRADE_ORDER.index(grade) >= _GRADE_ORDER.index(minimum)
    except ValueError:
        return False


def refresh_prices(store: Storage, tickers: list[str] | None = None) -> dict[str, pd.DataFrame]:
    """Batch-fetch all watchlist tickers and upsert them into storage."""
    tickers = tickers or load_watchlist().tickers
    frames = fetch_many(tickers)
    for ticker, df in frames.items():
        store.upsert_prices(ticker, df)
    return frames


def evaluate_signals(
    store: Storage, price_map: dict[str, pd.DataFrame] | None = None
) -> CycleResult:
    """Run the orchestrator. If ``price_map`` is None, read the latest prices from the DB."""
    if price_map is None:
        price_map = {t: store.get_prices(t) for t in load_watchlist().tickers}
        price_map = {t: df for t, df in price_map.items() if not df.empty}
    # Wire in the real (network) scorecard + evidence providers. The engine fetches
    # benchmarks once and earnings/news per gradeable ticker; the historical backtest
    # is cached in the DB and refreshed weekly.
    fetcher = backtest.make_fetcher()
    engine = SignalEngine(
        store,
        benchmark_provider=benchmarks.fetch_benchmarks,
        earnings_provider=earnings.days_to_earnings,
        historical_provider=(
            (lambda t, s, st: backtest.compute_stats(t, s, st, store=store, fetcher=fetcher))
            if settings.enable_backtest
            else None
        ),
        earnings_beat_provider=news.earnings_beat,
        news_provider=news.recent_headlines,
        benchmark_price_provider=_latest_benchmark_close,
    )
    return engine.run_cycle(price_map)


def run_portfolio_backtest(
    tickers: list[str] | None = None,
    *,
    fetcher: Callable[[str, int], pd.DataFrame] | None = None,
    cadence: str | None = None,
    years: int | None = None,
) -> BacktestResult:
    """Fetch extended history and replay the portfolio mechanism vs VOO (Session 14).

    Network-heavy (one extended fetch per ticker + the benchmark), so this is a
    manual/dashboard action, not part of the daily cycle. ``fetcher`` is injected
    in tests to stay offline; failures per ticker are skipped, not fatal.
    """
    tickers = tickers or load_watchlist().tickers
    years = years or settings.backtest_years
    bars = int(years * settings.trading_days_per_year * 1.1) + 5
    fetch = fetcher or (lambda t, b: fetch_prices(t, bars=b))

    def _safe(ticker: str) -> pd.DataFrame:
        try:
            return fetch(ticker, bars)
        except DataFetchError as exc:
            logger.warning("backtest fetch failed for {}: {}", ticker, exc)
            return pd.DataFrame()

    price_map = {t: df for t in tickers if not (df := _safe(t)).empty}
    benchmark_df = _safe(settings.portfolio_benchmark)
    if benchmark_df.empty:
        logger.warning("backtest benchmark {} unavailable", settings.portfolio_benchmark)
        return BacktestResult()
    return backtest_portfolio.run_backtest(
        price_map, benchmark_df, cadence=cadence, years=years
    )


def _latest_benchmark_close() -> float | None:
    """Latest close of the portfolio benchmark (VOO) for the NAV overlay."""
    from src.core.data import DataFetchError, fetch_prices

    try:
        df = fetch_prices(settings.portfolio_benchmark, bars=5)
    except DataFetchError:
        return None
    return None if df.empty else float(df["close"].iloc[-1])


def fire_alerts(result: CycleResult) -> int:
    """Dispatch the cycle's alerts to all enabled notification channels."""
    return notify.dispatch(result.alerts)


@dataclass
class ValidationReport:
    """Result of a startup watchlist/config check (see :func:`validate_watchlist`)."""

    ok: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)  # ticker -> reason

    @property
    def all_ok(self) -> bool:
        return not self.failed

    def summary(self) -> str:
        n = len(self.ok) + len(self.failed)
        line = f"watchlist: {len(self.ok)}/{n} tickers fetchable"
        if self.failed:
            detail = ", ".join(f"{t} ({why})" for t, why in self.failed.items())
            return f"{line} — UNFETCHABLE: {detail}"
        return line + " — all OK"


def validate_watchlist(
    fetcher: Callable[[str, int], pd.DataFrame] | None = None,
) -> ValidationReport:
    """Load the watchlist (validating its schema) and check every ticker fetches.

    Loading raises on a malformed YAML/schema; reachability problems are collected
    per ticker rather than raised, so one bad symbol doesn't mask the rest.
    A small bar count keeps the check fast — we only need to confirm data exists.
    """
    fetch = fetcher or (lambda t, bars: fetch_prices(t, bars))
    report = ValidationReport()
    for ticker in load_watchlist().tickers:
        try:
            df = fetch(ticker, 5)
            if df.empty:
                report.failed[ticker] = "no data"
            else:
                report.ok.append(ticker)
        except DataFetchError as exc:
            report.failed[ticker] = str(exc)
        except Exception as exc:  # noqa: BLE001 - report, don't abort, on any provider error
            report.failed[ticker] = f"{type(exc).__name__}: {exc}"
    return report


def run_once(store: Storage | None = None, *, fetch: bool = True) -> CycleResult:
    """One full evaluation cycle: (optionally fetch) -> evaluate -> alert -> summarize."""
    store = store or Storage()
    if fetch:
        frames = refresh_prices(store)
        result = evaluate_signals(store, frames)
    else:
        result = evaluate_signals(store)

    fire_alerts(result)
    notify.log_portfolio_summary(result)
    logger.info(
        "cycle done: {} tickers, {} signals, {} alerts ({} suppressed) "
        "(date={}, regime={}, exposure={:.0%}) | statuses={}",
        result.n_tickers,
        result.n_signals,
        len(result.alerts),
        result.n_suppressed,
        result.bar_date,
        result.regime_label,
        result.exposure,
        result.status_counts,
    )
    return result


# --------------------------------------------------------------------------- #
# Session 15 — autonomous paper trading engine
# --------------------------------------------------------------------------- #
def monitor_positions(
    book: PaperBook,
    *,
    price_provider: Callable[[str], float | None],
    on: Date,
    slippage_fn: SlippageFn = _default_slippage,
    notify_events: bool = False,
) -> list[PaperTrade]:
    """Intraday stop/target surveillance on OPEN positions (every ~5 min).

    A stop hit closes at the *stop level* (not the next-bar open); a target hit
    closes at the *target level*. Stop takes priority. A position already flagged
    for a queued daily exit is left for the market-open job. Returns trades closed.
    """
    closed: list[PaperTrade] = []
    for t in book.open_trades():
        if t.pending_exit_reason:
            continue  # already queued to close at the next open
        price = price_provider(t.ticker)
        if price is None:
            continue
        if t.stop_price and price <= t.stop_price:
            done = book.close_trade(
                t, exit_price=t.stop_price, exit_reason="EXIT_STOP",
                slippage_bps=slippage_fn(t.ticker, SELL, t.shares * t.stop_price), on=on,
            )
            closed.append(done)
        elif t.target_price and price >= t.target_price:
            done = book.close_trade(
                t, exit_price=t.target_price, exit_reason="EXIT_TARGET",
                slippage_bps=slippage_fn(t.ticker, SELL, t.shares * t.target_price), on=on,
            )
            closed.append(done)
    if notify_events:
        for t in closed:
            notify.notify_trade_closed(t)
    return closed


def execute_market_open(
    book: PaperBook,
    *,
    on: Date,
    open_price_provider: Callable[[str, Date], float | None],
    slippage_fn: SlippageFn = _default_slippage,
    notify_events: bool = False,
) -> tuple[list[PaperTrade], list[PaperTrade]]:
    """The 9:31 fill job: process overnight gaps + queued exits, then fill entries.

    Order matters — exits free up cash before new entries are filled:
      1. OPEN trades with a queued daily exit close at the open.
      2. OPEN trades that gapped through a stop/target overnight close at the open
         (gap-protected: a stop at $19.50 gapping to a $17.00 open fills at $17.00).
      3. PENDING entries fill at the open + slippage (PENDING → OPEN).
    Returns ``(opened, closed)``.
    """
    closed: list[PaperTrade] = []
    for t in book.open_trades():
        op = open_price_provider(t.ticker, on)
        if op is None:
            continue
        reason, gap_note, fill = "", "", op
        if t.pending_exit_reason:
            reason = t.pending_exit_reason
        elif t.stop_price and op <= t.stop_price:
            reason = "EXIT_STOP"
            fill = check_gap(t.stop_price, op, SELL)
            if op < t.stop_price:
                gap_note = f"gapped through stop {t.stop_price:.2f} -> filled at open {op:.2f}"
        elif t.target_price and op >= t.target_price:
            reason = "EXIT_TARGET"
            fill = max(t.target_price, op)  # favorable gap fills at the better open
            if op > t.target_price:
                gap_note = f"gapped above target {t.target_price:.2f} -> filled at open {op:.2f}"
        if reason:
            done = book.close_trade(
                t, exit_price=fill, exit_reason=reason,
                slippage_bps=slippage_fn(t.ticker, SELL, t.shares * fill), on=on,
                gap_note=gap_note,
            )
            closed.append(done)

    opened: list[PaperTrade] = []
    for t in book.pending_trades():
        op = open_price_provider(t.ticker, on)
        if op is None:
            continue
        done = book.execute_pending(
            t, open_price=op, slippage_bps=slippage_fn(t.ticker, BUY, t.cost_basis), on=on
        )
        opened.append(done)

    if notify_events:
        for t in closed:
            notify.notify_trade_closed(t)
        for t in opened:
            notify.notify_trade_opened(t)
    return opened, closed


def queue_entries(
    book: PaperBook,
    store: Storage,
    *,
    on: Date,
    regime_label: str,
) -> list[PaperTrade]:
    """Create PENDING entries from the day's graded candidates (best rank first).

    A name enters only when every gate passes: regime is not RISK_OFF, composite
    ≥ ``paper_min_score``, grade ≥ ``paper_min_grade``, it isn't already active,
    and the budget can fund at least ``min_position_size``. The full decision
    state is snapshotted into the trade immutably.
    """
    if regime_label == "RISK_OFF":
        return []
    created: list[PaperTrade] = []
    for ds in store.get_daily_scores(on):  # best rank first
        if ds.score < settings.paper_min_score:
            continue
        if book.has_active(ds.ticker):
            continue
        dossier = store.latest_dossier(ds.ticker)
        if dossier is None or dossier.date != on or not _grade_ok(dossier.grade, settings.paper_min_grade):
            continue
        plan = json.loads(dossier.summary or "{}").get("trade_plan", {})
        stop = float(plan.get("stop") or 0.0)
        target = float(plan.get("target") or 0.0)
        planned = book.size_position(ds.score)
        if planned <= 0:
            continue  # out of budget — stop trying to add more names
        created.append(
            book.create_pending(
                ticker=ds.ticker,
                strategy="composite",
                signal_id=None,
                snapshot={
                    "composite": ds.score,
                    "rank": ds.rank,
                    "grade": dossier.grade,
                    "regime": regime_label,
                    "dossier": json.loads(dossier.summary or "{}"),
                },
                planned_dollars=planned,
                stop_price=stop,
                target_price=target,
            )
        )
    return created


def queue_daily_exits(
    book: PaperBook,
    store: Storage,
    *,
    on: Date,
    regime_label: str,
    price_map: dict[str, pd.DataFrame] | None = None,
) -> list[PaperTrade]:
    """Flag OPEN positions for a next-open exit on any daily exit condition.

    Priority: 50-EMA loss → RISK_OFF → RS rotation (past ``paper_exit_rank``) →
    time stop → grade dropped to AVOID. Sets ``pending_exit_reason``; the actual
    close happens at the next market open.
    """
    flagged: list[PaperTrade] = []
    rank_of = {ds.ticker: ds.rank for ds in store.get_daily_scores(on)}
    for t in book.open_trades():
        if t.pending_exit_reason:
            continue
        reason = _daily_exit_reason(t, store, on=on, regime_label=regime_label, rank_of=rank_of, price_map=price_map)
        if reason:
            t.pending_exit_reason = reason
            store.update_paper_trade(t)
            flagged.append(t)
    return flagged


def _daily_exit_reason(
    t: PaperTrade,
    store: Storage,
    *,
    on: Date,
    regime_label: str,
    rank_of: dict[str, int],
    price_map: dict[str, pd.DataFrame] | None,
) -> str:
    # 50-EMA loss
    df = (price_map or {}).get(t.ticker)
    if df is None:
        df = store.get_prices(t.ticker)
    if df is not None and not df.empty and len(df) >= 50:
        ema50 = float(df["close"].ewm(span=50, adjust=False).mean().iloc[-1])
        if float(df["close"].iloc[-1]) < ema50:
            return "EXIT_EMA"
    # regime
    if regime_label == "RISK_OFF":
        return "EXIT_REGIME"
    # RS rotation
    rank = rank_of.get(t.ticker)
    if rank is not None and rank > settings.paper_exit_rank:
        return "EXIT_ROTATION"
    # time stop
    if t.entry_date is not None and (on - t.entry_date).days > settings.time_stop_days:
        return "EXIT_TIME"
    # grade to AVOID
    dossier = store.latest_dossier(t.ticker)
    if dossier is not None and dossier.date == on and dossier.grade == "AVOID":
        return "EXIT_QUALITY"
    return ""


def record_cashbook(
    book: PaperBook,
    store: Storage,
    *,
    on: Date,
    regime_label: str,
    exposure_pct: float,
    open_prices: dict[str, float],
    voo_price: float | None,
) -> CashbookEntry:
    """Persist the day's paper-account snapshot for the NAV-vs-VOO equity curve.

    The VOO benchmark anchors on the first recorded day (so it starts at the
    budget); a missing benchmark price degrades the VOO nav to the budget rather
    than crashing the cycle.
    """
    invested = book.invested_value(open_prices)
    total_nav = book.current_nav(open_prices)
    cash_end = total_nav - invested
    prev = store.latest_cashbook()
    cash_start = prev.cash_end if prev is not None else book.budget
    if voo_price and voo_price > 0:
        voo_nav = book.voo_nav_since_start(voo_price)
        voo_px = voo_price
    else:
        voo_nav = book.budget
        voo_px = 0.0
    return store.upsert_cashbook(
        date=on,
        cash_start=cash_start,
        cash_end=cash_end,
        invested_value=invested,
        total_nav=total_nav,
        voo_nav=voo_nav,
        voo_price=voo_px,
        regime=regime_label,
        exposure_pct=exposure_pct,
    )


def daily_eval(store: Storage | None = None, *, fetch: bool = True) -> CycleResult:
    """The daily-close job: run the signal cycle, then queue paper entries + exits.

    Entries become PENDING for the next open; daily exits flag OPEN positions for
    a next-open close. Intraday stop/target hits are handled by the monitor. A
    daily cashbook snapshot is persisted for the NAV-vs-VOO equity curve.
    """
    store = store or Storage()
    result = run_once(store, fetch=fetch)
    if settings.enable_paper_trading and result.bar_date is not None:
        if settings.trade_instrument in ("stock", "both"):
            book = PaperBook(store)
            queue_daily_exits(
                book, store, on=result.bar_date, regime_label=result.regime_label
            )
            queue_entries(book, store, on=result.bar_date, regime_label=result.regime_label)
            open_prices = {
                t.ticker: px
                for t in book.open_trades()
                if (px := _latest_close(store, t.ticker)) is not None
            }
            record_cashbook(
                book,
                store,
                on=result.bar_date,
                regime_label=result.regime_label,
                exposure_pct=result.exposure,
                open_prices=open_prices,
                voo_price=_benchmark_price(),
            )
        if settings.enable_options and settings.trade_instrument in ("option", "both"):
            obook = OptionBook(store)
            queue_option_entries(
                obook, store, on=result.bar_date, regime_label=result.regime_label,
                price_provider=store.get_prices,
            )
    return result


def _benchmark_price() -> float | None:
    """Latest close for the portfolio benchmark (VOO), or None if unavailable."""
    return execution.get_current_price(settings.portfolio_benchmark)


def daily_summary(store: Storage | None = None, *, on: Date | None = None) -> str:
    """One end-of-day notification: NAV, vs VOO, open count, today's closed P&L."""
    store = store or Storage()
    book = PaperBook(store)
    prices = {
        t.ticker: _latest_close(store, t.ticker) for t in book.open_trades()
    }
    nav = book.current_nav({k: v for k, v in prices.items() if v is not None})
    closed_today = [
        t for t in book.closed_trades() if on is not None and t.exit_date == on
    ]
    realized = sum(t.pnl_dollars for t in closed_today)
    line = notify.notify_daily_summary(
        nav=nav,
        budget=book.budget,
        open_count=len(book.open_trades()),
        closed_today=len(closed_today),
        realized_today=realized,
        pending=len(book.pending_trades()),
    )
    return line


def _latest_close(store: Storage, ticker: str) -> float | None:
    df = store.get_prices(ticker)
    if df.empty:
        return None
    return float(df["close"].iloc[-1])


# --------------------------------------------------------------------------- #
# Session 16 — options expression layer jobs
# --------------------------------------------------------------------------- #
def _default_chain_provider(ticker: str, dte: int, as_of: Date) -> dict[str, Any] | None:
    return option_chain.fetch_chain(ticker, target_dte=dte, as_of=as_of)


def queue_option_entries(
    book: OptionBook,
    store: Storage,
    *,
    on: Date,
    regime_label: str,
    price_provider: PriceFrameProvider,
    chain_provider: ChainProvider | None = None,
) -> list[OptionTrade]:
    """Queue PENDING long calls from the day's graded candidates (same gates as stock)."""
    if regime_label == "RISK_OFF":
        return []
    chain_provider = chain_provider or _default_chain_provider
    created: list[OptionTrade] = []
    for ds in store.get_daily_scores(on):
        if ds.score < settings.paper_min_score:
            continue
        if book.has_active(ds.ticker):
            continue
        dossier = store.latest_dossier(ds.ticker)
        if dossier is None or dossier.date != on or not _grade_ok(dossier.grade, settings.paper_min_grade):
            continue
        df = price_provider(ds.ticker)
        if df is None or df.empty:
            continue
        plan = json.loads(dossier.summary or "{}").get("trade_plan", {})
        stop = float(plan.get("stop") or 0.0)
        target = float(plan.get("target") or 0.0)
        chain = chain_provider(ds.ticker, settings.option_target_dte, on)
        iv = option_vol.realized_vol(df)
        if chain is not None and chain.get("calls"):
            atm = min(chain["calls"], key=lambda c: abs(float(c["strike"]) - float(df["close"].iloc[-1])))
            if atm.get("iv"):
                iv = float(atm["iv"])
        contract = select_contract(
            ds.ticker, df, as_of=on, chain=chain,
            target_delta=settings.option_target_delta,
            target_dte=settings.option_target_dte, iv=iv,
            risk_free_rate=settings.risk_free_rate,
        )
        est_prem, _ = entry_premium(
            contract, underlying=float(df["close"].iloc[-1]), on=on,
            chain=chain, risk_free_rate=settings.risk_free_rate,
        )
        # Fund each name up to the per-name cap; create_pending floors to whole
        # contracts and returns None if not even one contract fits.
        trade = book.create_pending(
            ticker=ds.ticker, strategy="composite", contract=contract,
            snapshot={"composite": ds.score, "rank": ds.rank, "grade": dossier.grade,
                      "regime": regime_label, "dossier": json.loads(dossier.summary or "{}")},
            planned_dollars=settings.max_position_pct * book.budget,
            entry_premium_est=est_prem, underlying_stop=stop, underlying_target=target,
        )
        if trade is not None:
            created.append(trade)
    return created


def execute_option_open(
    book: OptionBook,
    *,
    on: Date,
    underlying_provider: UnderlyingDateProvider,
    chain_provider: ChainProvider | None = None,
    notify_events: bool = False,
) -> list[OptionTrade]:
    """Fill PENDING long calls at the next open's underlying + hybrid premium."""
    chain_provider = chain_provider or _default_chain_provider
    opened: list[OptionTrade] = []
    for t in book.pending_trades():
        under = underlying_provider(t.ticker, on)
        if under is None:
            continue
        contract = OptionContract(
            option_type=t.option_type, strike=t.strike, expiry=t.expiry or on,
            dte=t.dte_at_entry, iv=t.entry_iv, delta=t.entry_delta, source=t.price_source,
        )
        chain = chain_provider(t.ticker, settings.option_target_dte, on)
        prem, source = entry_premium(
            contract, underlying=under, on=on, chain=chain, risk_free_rate=settings.risk_free_rate,
        )
        bps = 0.0 if source == "chain" else settings.option_slippage_bps_model
        fill = prem * (1.0 + bps / 10_000.0)
        t.price_source = source
        done = book.execute_pending(t, fill_premium=fill, on=on, underlying=under)
        opened.append(done)
    if notify_events:
        for t in opened:
            notify.notify_option_opened(t)
    return opened


def monitor_option_positions(
    book: OptionBook,
    *,
    on: Date,
    underlying_provider: UnderlyingProvider,
    notify_events: bool = False,
) -> list[OptionTrade]:
    """Mark OPEN calls (Black-Scholes) and close the first that trips an exit rule."""
    closed: list[OptionTrade] = []
    for t in book.open_trades():
        under = underlying_provider(t.ticker)
        if under is None:
            continue
        prem = mark_premium(
            t, underlying=under, on=on, iv=t.entry_iv, risk_free_rate=settings.risk_free_rate,
        )
        reason = evaluate_exit(t, underlying=under, premium=prem, on=on)
        if reason:
            exit_prem = max(0.0, under - t.strike) if reason == "EXIT_EXPIRY" else prem
            done = book.close_trade(
                t, exit_premium=exit_prem, exit_reason=reason, on=on, underlying=under,
            )
            closed.append(done)
    if notify_events:
        for t in closed:
            notify.notify_option_closed(t)
    return closed


def option_daily_summary(
    store: Storage,
    *,
    on: Date,
    underlying_provider: UnderlyingProvider,
    voo_price: float | None,
) -> str:
    """Mark the option book to NAV, write an option_cashbook row, notify once."""
    book = OptionBook(store)
    marks: dict[int, float] = {}
    for t in book.open_trades():
        under = underlying_provider(t.ticker)
        if under is None:
            continue
        marks[t.trade_id or -1] = mark_premium(
            t, underlying=under, on=on, iv=t.entry_iv, risk_free_rate=settings.risk_free_rate,
        )
    nav = book.current_nav(marks)
    invested = book.invested_value(marks)
    history = store.get_option_cashbook()
    voo_start = next((c.voo_price for c in history if c.voo_price), voo_price)
    voo_nav = book.voo_nav(voo_start, voo_price) if (voo_price and voo_start) else book.budget
    reg = store.latest_regime()
    regime = reg.label if reg is not None else ""
    store.upsert_option_cashbook(
        date=on, total_nav=nav, voo_nav=voo_nav, invested_value=invested,
        regime=regime, voo_price=voo_price or 0.0,
    )
    closed_today = [t for t in book.closed_trades() if t.exit_date == on]
    realized = sum(t.pnl_dollars for t in closed_today)
    return notify.notify_daily_summary(
        nav=nav, budget=book.budget, open_count=len(book.open_trades()),
        closed_today=len(closed_today), realized_today=realized,
    )


# --------------------------------------------------------------------------- #
# Trading-calendar guard + scheduler entry points
# --------------------------------------------------------------------------- #
def _easter(year: int) -> Date:
    """Gregorian Easter Sunday (Anonymous algorithm) — anchors Good Friday."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month, day = divmod(h + m - 7 * n + 114, 31)
    return Date(year, month, day + 1)


def _observed(d: Date) -> Date:
    """NYSE observance: a Saturday holiday shifts to Friday, a Sunday to Monday."""
    from datetime import timedelta

    if d.weekday() == 5:  # Saturday
        return d - timedelta(days=1)
    if d.weekday() == 6:  # Sunday
        return d + timedelta(days=1)
    return d


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> Date:
    """The ``n``-th ``weekday`` (Mon=0) of a month (n>=1)."""
    from datetime import timedelta

    first = Date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> Date:
    """The last ``weekday`` (Mon=0) of a month."""
    from datetime import timedelta

    nxt = Date(year + 1, 1, 1) if month == 12 else Date(year, month + 1, 1)
    last = nxt - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


@lru_cache(maxsize=8)
def _nyse_holidays(year: int) -> frozenset[Date]:
    """NYSE market holidays for ``year`` (observed dates). Zero-dependency."""
    from datetime import timedelta

    good_friday = _easter(year) - timedelta(days=2)
    days = {
        _observed(Date(year, 1, 1)),  # New Year's Day
        _nth_weekday(year, 1, 0, 3),  # MLK Day (3rd Mon Jan)
        _nth_weekday(year, 2, 0, 3),  # Washington's Birthday (3rd Mon Feb)
        good_friday,
        _last_weekday(year, 5, 0),  # Memorial Day (last Mon May)
        _nth_weekday(year, 9, 0, 1),  # Labor Day (1st Mon Sep)
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving (4th Thu Nov)
        _observed(Date(year, 12, 25)),  # Christmas
        _observed(Date(year, 7, 4)),  # Independence Day
    }
    if year >= 2022:  # Juneteenth became an NYSE holiday in 2022
        days.add(_observed(Date(year, 6, 19)))
    return frozenset(days)


def is_trading_day(d: Date) -> bool:
    """True when ``d`` is a US equity trading day (weekday + not an NYSE holiday)."""
    if d.weekday() >= 5:  # Saturday / Sunday
        return False
    return d not in _nyse_holidays(d.year)


def _today_market() -> Date:
    return datetime.now(ZoneInfo(settings.market_tz)).date()


def run_daily_eval(store: Storage | None = None) -> CycleResult | None:
    """Scheduler entry: the daily-close cycle + paper entry/exit queueing."""
    on = _today_market()
    if not is_trading_day(on):
        logger.info("skip daily eval — {} is not a trading day", on)
        return None
    return daily_eval(store)


def run_market_open(store: Storage | None = None) -> None:
    """Scheduler entry (~9:31): fill PENDING entries + queued/gapped exits."""
    on = _today_market()
    if not (settings.enable_paper_trading and is_trading_day(on)):
        return
    store = store or Storage()
    book = PaperBook(store)
    if not (book.pending_trades() or book.open_trades()):
        return
    execute_market_open(
        book, on=on, open_price_provider=execution.get_open_price, notify_events=True
    )


def run_monitor(store: Storage | None = None) -> None:
    """Scheduler entry (every ~5 min): intraday stop/target surveillance."""
    on = _today_market()
    if not (settings.enable_paper_trading and is_trading_day(on)):
        return
    store = store or Storage()
    book = PaperBook(store)
    if not book.open_trades():
        return
    monitor_positions(
        book, price_provider=execution.get_current_price, on=on, notify_events=True
    )


def run_daily_summary(store: Storage | None = None) -> None:
    """Scheduler entry (~16:30): one end-of-day paper summary notification."""
    on = _today_market()
    if not (settings.enable_paper_trading and is_trading_day(on)):
        return
    daily_summary(store, on=on)


# --------------------------------------------------------------------------- #
# Session 16 — options scheduler entry points
# --------------------------------------------------------------------------- #
def _options_active() -> bool:
    return settings.enable_options and settings.trade_instrument in ("option", "both")


def _option_underlying_now(ticker: str) -> float | None:
    return execution.get_current_price(ticker)


def run_option_market_open(store: Storage | None = None) -> None:
    """Scheduler entry (~9:31): fill PENDING option entries at the open."""
    on = _today_market()
    if not (_options_active() and is_trading_day(on)):
        return
    store = store or Storage()
    book = OptionBook(store)
    if not book.pending_trades():
        return
    execute_option_open(
        book, on=on,
        underlying_provider=lambda t, d: execution.get_open_price(t, d),
        notify_events=True,
    )


def run_option_monitor(store: Storage | None = None) -> None:
    """Scheduler entry (every ~5 min): mark + exit OPEN option positions."""
    on = _today_market()
    if not (_options_active() and is_trading_day(on)):
        return
    store = store or Storage()
    book = OptionBook(store)
    if not book.open_trades():
        return
    monitor_option_positions(book, on=on, underlying_provider=_option_underlying_now, notify_events=True)


def run_option_summary(store: Storage | None = None) -> None:
    """Scheduler entry (~16:30): option NAV summary + cashbook row."""
    on = _today_market()
    if not (_options_active() and is_trading_day(on)):
        return
    store = store or Storage()
    voo = execution.get_current_price(settings.portfolio_benchmark)
    option_daily_summary(store, on=on, underlying_provider=_option_underlying_now, voo_price=voo)
