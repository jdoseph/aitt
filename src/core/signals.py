"""Signal orchestrator.

For each ticker, runs all four strategies, persists their classifications
(deduplicated to one row per ticker/strategy/day via upsert), detects transitions
into alert-worthy statuses, writes the resulting alerts, and returns them sorted
by confidence (3-star first).

Alert policy lives in :func:`alert_decision` — the single place that decides
whether a classified status is worth notifying about, applying the trend filter,
ATH-freshness gate, volume requirement, and confidence threshold from config.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date as Date
from typing import Any

import pandas as pd
from loguru import logger

from src.core import (
    accumulation as accumulation_mod,
    benchmarks as bm,
    exposure as exposure_mod,
    gating,
    market,
    multitimeframe as mtf,
    ranking,
    regime as regime_mod,
    scorecard,
    scoring,
    sizing as sizing_mod,
    stage as stage_mod,
)
from src.core.accumulation import AccumulationResult
from src.core.backtest import HistoricalStat
from src.core.indicators import compute_metrics
from src.core.market import ThesisHealth
from src.core.ranking import RankedOpportunity, ScoredName
from src.core.stage import StageResult
from src.core.config import settings
from src.core.dossier import Dossier, DossierContext, build_dossier
from src.core.exposure import ExposureResult
from src.core.portfolio import PaperPortfolio
from src.core.regime import Regime
from src.core.scorecard import ScoreContext
from src.core.sizing import Candidate, SizingPlan
from src.core.storage import Storage
from src.core.strategies.ath_pullback import ATHPullbackStrategy
from src.core.strategies.base import NO_SIGNAL, Signal, Strategy
from src.core.strategies.consolidation_breakout import ConsolidationBreakoutStrategy
from src.core.strategies.ema_pullback import EMAPullbackStrategy
from src.core.strategies.ipo_base import IPOBaseStrategy
from src.core.watchlist import Watchlist, load_watchlist

# Statuses worth grading with the full scorecard (the alert-worthy entry states).
GRADEABLE_STATUSES: frozenset[str] = frozenset(
    {"AT_9_EMA", "AT_21_EMA", "ENTRY_ZONE", "DEEP_PULLBACK", "BREAKOUT", "IPO_BREAKOUT"}
)
_ACTION_RANK = {"HIGH-QUALITY": 3, "DECENT": 2, "MARGINAL": 1, "AVOID": 0}


def _safe_call(fn: Callable[..., Any], *args: Any, label: str, default: Any) -> Any:
    """Call a (possibly network) provider, logging and swallowing failures."""
    try:
        return fn(*args)
    except Exception as exc:  # noqa: BLE001 - provider resilience boundary
        logger.debug("{} provider failed for {}: {}", label, args, exc)
        return default

DEFAULT_STRATEGIES: tuple[type[Strategy], ...] = (
    EMAPullbackStrategy,
    ATHPullbackStrategy,
    ConsolidationBreakoutStrategy,
    IPOBaseStrategy,
)

# Severity ranking for sorting (lower = shown first within equal confidence).
_SEVERITY_RANK = {"entry": 0, "secondary": 1, "warning": 2}


@dataclass(frozen=True)
class Alert:
    """A fired alert returned from a cycle (also persisted to the alerts table)."""

    ticker: str
    strategy: str
    status: str
    severity: str  # entry | secondary | warning
    message: str
    confidence: int
    patterns: list[str]
    date: Date
    action: str | None = None  # scorecard grade, if scored (capped in downgrade mode)
    scorecard_lines: list[str] = field(default_factory=list)
    bear_reasons: list[str] = field(default_factory=list)  # top "why NOT buy" factors
    regime: str = ""  # market-regime label at fire time
    gate_flags: list[str] = field(default_factory=list)  # disqualifiers (downgrade mode)
    score: float | None = None  # 0-100 composite (Session 11)
    rank: int | None = None  # cross-sectional rank, 1 = best
    n_ranked: int = 0  # cohort size for the rank

    def score_label(self) -> str:
        """e.g. 'NVDA 91/100 · #2 of 41' — empty when unscored."""
        if self.score is None or self.rank is None:
            return ""
        return f"{self.score:.0f}/100 · #{self.rank} of {self.n_ranked}"


@dataclass
class CycleResult:
    bar_date: Date | None = None
    n_tickers: int = 0
    n_signals: int = 0
    status_counts: dict[str, int] = field(default_factory=dict)
    alerts: list[Alert] = field(default_factory=list)
    breadth_summary: str = ""
    leading_layers: list[str] = field(default_factory=list)
    dossiers: dict[str, Dossier] = field(default_factory=dict)  # ticker -> dossier
    regime_label: str = regime_mod.NEUTRAL
    regime_summary: str = ""
    n_suppressed: int = 0  # alerts suppressed by the regime gate / disqualifiers
    # Session 11: cross-sectional scoring + rotation.
    scores: dict[str, float] = field(default_factory=dict)  # ticker -> composite
    ranked: list[RankedOpportunity] = field(default_factory=list)  # best -> worst
    allocation: dict[str, float] = field(default_factory=dict)  # ticker -> suggested %
    layer_strength: dict[str, float] = field(default_factory=dict)
    layer_rotation: dict[str, float] = field(default_factory=dict)
    thesis: ThesisHealth | None = None
    # Session 13: paper-portfolio exposure management.
    exposure: float = 0.0  # 0-1 target invested fraction
    exposure_result: ExposureResult | None = None
    portfolio_nav: float = 0.0
    portfolio_weights: dict[str, float] = field(default_factory=dict)  # ticker -> current weight
    rebalance_suggestions: list[str] = field(default_factory=list)


def _stars(n: int) -> str:
    return "⭐" * n if n > 0 else "—"


def _build_message(sig: Signal, severity: str) -> str:
    d = sig.details
    pat = f", {', '.join(sig.patterns_detected)}" if sig.patterns_detected else ""
    stars = _stars(sig.confidence)
    s = sig.status
    if sig.strategy_name == "ema_pullback":
        ema = "21 EMA" if s == "AT_21_EMA" else "9 EMA"
        return f"{sig.ticker} at {ema} ({d.get('dist_ema_21_pct')}% vs 21){pat} {stars}"
    if sig.strategy_name == "ath_pullback":
        tag = "entry zone" if s == "ENTRY_ZONE" else "deep pullback"
        return f"{sig.ticker} {tag}: -{d.get('pullback_pct')}% from ATH {d.get('ath')}{pat} {stars}"
    if sig.strategy_name == "consolidation_breakout":
        if s == "BREAKOUT":
            return (
                f"{sig.ticker} BREAKOUT above {d.get('range_high')} "
                f"({d.get('days_in_range')}d base, vol x{d.get('vol_ratio')}){pat} {stars}"
            )
        return (
            f"{sig.ticker} BREAKDOWN below {d.get('range_low')} "
            f"(vol x{d.get('vol_ratio')}) — thesis may be broken"
        )
    if sig.strategy_name == "ipo_base":
        return (
            f"{sig.ticker} IPO BREAKOUT above {d.get('ipo_high')} "
            f"(vol x{d.get('vol_ratio')}){pat} {stars}"
        )
    return f"{sig.ticker} {s} {stars}"


def alert_decision(sig: Signal) -> tuple[str, str] | None:
    """Decide whether ``sig`` warrants an alert. Returns ``(severity, message)`` or None.

    Applies config gates: trend filter & volume (EMA), ATH freshness (ATH),
    and the minimum-confidence threshold (entry-grade alerts only — secondary
    and warning alerts bypass it so dips/breakdowns still surface).
    """
    s, strat, d = sig.status, sig.strategy_name, sig.details
    min_stars = settings.min_confidence_stars

    if strat == "ema_pullback" and s in ("AT_9_EMA", "AT_21_EMA"):
        if settings.use_trend_filter and d.get("trend_ok") is False:
            return None
        if settings.ema_require_volume and float(d.get("vol_ratio") or 0) < 1.0:
            return None
        if sig.confidence < min_stars:
            return None
        return "entry", _build_message(sig, "entry")

    if strat == "ath_pullback" and s in ("ENTRY_ZONE", "DEEP_PULLBACK"):
        if not d.get("ath_fresh"):
            return None  # stale high — uptrend not confirmed
        if s == "ENTRY_ZONE":
            if sig.confidence < min_stars:
                return None
            return "entry", _build_message(sig, "entry")
        return "secondary", _build_message(sig, "secondary")  # DEEP_PULLBACK

    if strat == "consolidation_breakout":
        if s == "BREAKOUT":
            if sig.confidence < min_stars:
                return None
            return "entry", _build_message(sig, "entry")
        if s == "BREAKDOWN":
            return "warning", _build_message(sig, "warning")

    if strat == "ipo_base" and s == "IPO_BREAKOUT":
        if sig.confidence < min_stars:
            return None
        return "entry", _build_message(sig, "entry")

    return None


@dataclass
class _Evaluated:
    ticker: str
    df: pd.DataFrame
    strategy: Strategy
    signal: Signal
    bar_date: Date  # signal.date, already known non-None at collection time


@dataclass
class _PendingAlert:
    """An alert decided in pass 2, finalized once dossiers (bear reasons) exist."""

    ev: _Evaluated
    severity: str
    message: str
    card: scorecard.Scorecard | None
    action: str | None = None  # possibly capped by the gate (downgrade mode)
    gate_flags: list[str] = field(default_factory=list)


# Action grades, worst -> best, for capping in downgrade mode.
_ACTION_ORDER = ["AVOID", "MARGINAL", "DECENT", "HIGH-QUALITY"]


def _cap_action(action: str | None, ceiling: str) -> str | None:
    """Lower ``action`` to ``ceiling`` if it currently grades higher."""
    if action is None or action not in _ACTION_ORDER or ceiling not in _ACTION_ORDER:
        return action
    return action if _ACTION_ORDER.index(action) <= _ACTION_ORDER.index(ceiling) else ceiling


@dataclass(frozen=True)
class _DeepSignals:
    """Session 12 deeper signals for one ticker (computed once, reused everywhere)."""

    stage: StageResult | None = None
    weekly: mtf.WeeklyTrend | None = None
    accumulation: AccumulationResult | None = None
    crowding: float | None = None


def _compute_deep(df: pd.DataFrame) -> _DeepSignals:
    stage = _safe_call(stage_mod.classify_stage, df, label="stage", default=None)
    weekly = _safe_call(mtf.weekly_trend, df, label="weekly", default=None)
    accumulation = _safe_call(
        accumulation_mod.accumulation_score, df, label="accumulation", default=None
    )
    m = _safe_call(compute_metrics, df, label="metrics", default=None)
    return _DeepSignals(
        stage=stage,
        weekly=weekly,
        accumulation=accumulation,
        crowding=None if m is None else m.crowding,
    )


class SignalEngine:
    """Runs all strategies over a price map and reconciles signals/alerts with the DB.

    Scorecard inputs (benchmarks, earnings) are injected as providers so the engine
    stays offline/deterministic in tests; the agent wires in the real network
    providers (see ``jobs.evaluate_signals``).
    """

    def __init__(
        self,
        store: Storage,
        strategies: tuple[type[Strategy], ...] | None = None,
        *,
        watchlist: Watchlist | None = None,
        benchmark_provider: Callable[[], dict[str, pd.DataFrame]] | None = None,
        earnings_provider: Callable[[str], int | None] | None = None,
        historical_provider: Callable[[str, str, str], HistoricalStat | None] | None = None,
        earnings_beat_provider: Callable[[str], str | None] | None = None,
        news_provider: Callable[[str], list[dict[str, Any]]] | None = None,
        benchmark_price_provider: Callable[[], float | None] | None = None,
        enable_scorecard: bool | None = None,
    ) -> None:
        self.store = store
        self.strategies: list[Strategy] = [cls() for cls in (strategies or DEFAULT_STRATEGIES)]
        self._watchlist = watchlist
        self.benchmark_provider = benchmark_provider or (lambda: {})
        # Session 13: latest benchmark (VOO) close for the NAV overlay (offline in tests).
        self.benchmark_price_provider = benchmark_price_provider or (lambda: None)
        self.earnings_provider = earnings_provider or (lambda _t: None)
        # Session 8 evidence providers (default no-ops keep the engine offline in tests).
        self.historical_provider = historical_provider or (lambda _t, _s, _st: None)
        self.earnings_beat_provider = earnings_beat_provider or (lambda _t: None)
        self.news_provider = news_provider or (lambda _t: [])
        self.enable_scorecard = (
            settings.enable_scorecard if enable_scorecard is None else enable_scorecard
        )

    def _watchlist_or_load(self) -> Watchlist:
        if self._watchlist is None:
            self._watchlist = load_watchlist()
        return self._watchlist

    def run_cycle(self, price_map: dict[str, pd.DataFrame]) -> CycleResult:
        result = CycleResult(n_tickers=len(price_map))

        # --- pass 1: evaluate everything (in memory) ---
        evaluated: list[_Evaluated] = []
        for ticker, df in price_map.items():
            for strat in self.strategies:
                sig = self._safe_evaluate(strat, ticker, df)
                if sig is None or sig.status == NO_SIGNAL or sig.date is None:
                    continue
                evaluated.append(_Evaluated(ticker, df, strat, sig, sig.date))

        # --- market context + scorecard inputs (computed once) ---
        ctx_market = market.compute_context(
            [e.signal for e in evaluated], self._watchlist_or_load()
        )
        layer_of = {e.ticker: e.layer for e in self._watchlist_or_load().entries}
        benchmarks = self.benchmark_provider() if self.enable_scorecard else {}
        # Canonical market-regime gate (Session 10): one read per cycle.
        regime = regime_mod.market_regime(benchmarks)
        result.regime_label = regime.label
        result.regime_summary = regime.summary()
        earnings_cache: dict[str, int | None] = {}
        beat_cache: dict[str, str | None] = {}
        news_cache: dict[str, list[dict[str, Any]]] = {}

        # --- pass 2: score, persist, collect pending alerts ---
        # Dossiers are per-ticker and need each ticker's full set of graded cards,
        # so we defer building them (and the in-memory Alert objects) until after
        # this loop. The signal/alert DB rows are still written inline here.
        cards_by_ticker: dict[str, list[tuple[Signal, scorecard.Scorecard]]] = defaultdict(list)
        signals_by_ticker: dict[str, list[Signal]] = defaultdict(list)
        df_by_ticker: dict[str, pd.DataFrame] = {}
        date_by_ticker: dict[str, Date] = {}
        pending: list[_PendingAlert] = []

        for ev in evaluated:
            sig, strat = ev.signal, ev.strategy
            signals_by_ticker[ev.ticker].append(sig)
            df_by_ticker[ev.ticker] = ev.df
            date_by_ticker[ev.ticker] = ev.bar_date
            card = None
            details = dict(sig.details)
            if self.enable_scorecard and sig.status in GRADEABLE_STATUSES:
                card = self._score(ev, ctx_market, benchmarks, layer_of, earnings_cache, beat_cache)
                cards_by_ticker[ev.ticker].append((sig, card))
                details["scorecard"] = card.to_summary()
                catalysts = self._catalysts(ev.ticker, beat_cache, news_cache)
                if catalysts["beat"] or catalysts["headlines"]:
                    details["catalysts"] = catalysts

            # --- regime gate / automatic disqualifiers ---
            decision = alert_decision(sig)
            dq, suppressed = self._gate(sig, card, regime, decision)
            action = _cap_action(card.action, settings.downgrade_cap_action) if (
                card and dq and settings.disqualifier_mode == "downgrade"
            ) else (card.action if card else None)
            if dq:
                details["disqualifiers"] = dq
                details["suppressed"] = suppressed

            prev = self.store.latest_signal(ev.ticker, strat.name)
            prev_status = prev.status if prev else None

            self.store.record_signal(
                ticker=sig.ticker,
                date=ev.bar_date,
                strategy=strat.name,
                status=sig.status,
                details=details,
                confidence=sig.confidence,
                patterns=sig.patterns_detected,
            )
            result.n_signals += 1
            result.bar_date = ev.bar_date
            result.status_counts[sig.status] = result.status_counts.get(sig.status, 0) + 1

            if decision and prev_status != sig.status:
                severity, message = decision
                if suppressed:
                    result.n_suppressed += 1
                    continue  # recorded as a signal, but fires no notification
                self.store.record_alert(
                    ticker=sig.ticker,
                    date=ev.bar_date,
                    strategy=strat.name,
                    status=sig.status,
                    message=message,
                    confidence=sig.confidence,
                    patterns=sig.patterns_detected,
                )
                pending.append(
                    _PendingAlert(
                        ev=ev, severity=severity, message=message, card=card,
                        action=action, gate_flags=dq,
                    )
                )

        # --- deeper signals computed once per graded ticker (Sessions 11/12) ---
        deep_by_ticker = {t: _compute_deep(df_by_ticker[t]) for t in cards_by_ticker}

        # --- dossiers: one per graded ticker (bull/bear case + trade plan) ---
        dossiers = self._build_dossiers(
            cards_by_ticker, signals_by_ticker, df_by_ticker, date_by_ticker,
            benchmarks, deep_by_ticker,
        )
        result.dossiers = dossiers

        # --- composite score + cross-sectional ranking (Session 11) ---
        scores, ranked, allocation = self._score_and_rank(
            cards_by_ticker, df_by_ticker, deep_by_ticker, benchmarks, layer_of,
            regime.label, result.bar_date,
        )
        result.scores, result.ranked, result.allocation = scores, ranked, allocation
        rank_by_ticker = {r.ticker: r for r in ranked}

        # --- layer strength + rotation + AI-thesis health (Session 11) ---
        all_signals = [e.signal for e in evaluated]
        result.layer_strength, result.layer_rotation, result.thesis = self._layers_and_thesis(
            all_signals, price_map, result.bar_date
        )

        # --- paper-portfolio exposure management (Session 13) ---
        if settings.enable_portfolio and result.bar_date is not None:
            self._portfolio_step(
                result, ranked, cards_by_ticker, df_by_ticker, price_map, regime, result.bar_date
            )

        # --- finalize alerts, folding in "why NOT buy" + composite score/rank ---
        for p in pending:
            dossier = dossiers.get(p.ev.ticker)
            card = p.card
            ro = rank_by_ticker.get(p.ev.ticker)
            result.alerts.append(
                Alert(
                    ticker=p.ev.ticker,
                    strategy=p.ev.strategy.name,
                    status=p.ev.signal.status,
                    severity=p.severity,
                    message=p.message,
                    confidence=p.ev.signal.confidence,
                    patterns=list(p.ev.signal.patterns_detected),
                    date=p.ev.bar_date,
                    action=p.action,
                    scorecard_lines=card.render_lines() if card else [],
                    bear_reasons=dossier.top_bear() if dossier else [],
                    regime=regime.label,
                    gate_flags=p.gate_flags,
                    score=ro.score if ro else None,
                    rank=ro.rank if ro else None,
                    n_ranked=ro.n if ro else 0,
                )
            )

        # Persist the regime label so the dashboard can show it without re-fetching.
        if result.bar_date is not None:
            self.store.upsert_regime(
                date=result.bar_date,
                label=regime.label,
                flags=regime.flags,
                summary=regime.summary(),
            )

        result.breadth_summary = ctx_market.breadth.summary()
        result.leading_layers = [k for k, _ in ctx_market.leadership[: settings.leading_layers_top_n]]
        # Confidence stays primary; the scorecard grade is the tie-breaker.
        result.alerts.sort(
            key=lambda a: (
                -a.confidence,
                -_ACTION_RANK.get(a.action or "", -1),
                _SEVERITY_RANK.get(a.severity, 9),
            )
        )
        return result

    def _build_dossiers(
        self,
        cards_by_ticker: dict[str, list[tuple[Signal, scorecard.Scorecard]]],
        signals_by_ticker: dict[str, list[Signal]],
        df_by_ticker: dict[str, pd.DataFrame],
        date_by_ticker: dict[str, Date],
        benchmarks: dict[str, pd.DataFrame],
        deep_by_ticker: dict[str, _DeepSignals],
    ) -> dict[str, Dossier]:
        """Build + persist one dossier per graded ticker (using its best scorecard)."""
        out: dict[str, Dossier] = {}
        for ticker, cards in cards_by_ticker.items():
            best_sig, best_card = max(
                cards, key=lambda sc: (_ACTION_RANK.get(sc[1].action, -1), sc[1].score)
            )
            deep = deep_by_ticker[ticker]
            ctx = DossierContext(
                df=df_by_ticker[ticker],
                benchmarks=benchmarks,
                best_signal=best_sig,
                stage=deep.stage,
                weekly=deep.weekly,
                accumulation=deep.accumulation,
            )
            dossier = build_dossier(ticker, signals_by_ticker[ticker], best_card, ctx)
            out[ticker] = dossier
            self.store.upsert_dossier(
                ticker=ticker,
                date=date_by_ticker[ticker],
                grade=dossier.grade,
                strongest_bull=dossier.strongest_bull or "",
                strongest_bear=dossier.strongest_bear or "",
                summary=dossier.to_summary(),
            )
        return out

    def _score_and_rank(
        self,
        cards_by_ticker: dict[str, list[tuple[Signal, scorecard.Scorecard]]],
        df_by_ticker: dict[str, pd.DataFrame],
        deep_by_ticker: dict[str, _DeepSignals],
        benchmarks: dict[str, pd.DataFrame],
        layer_of: dict[str, str],
        regime_label: str,
        bar_date: Date | None,
    ) -> tuple[dict[str, float], list[RankedOpportunity], dict[str, float]]:
        """Composite score + cross-sectional rank for every graded ticker."""
        capex_of = {e.ticker: e.capex_exposure for e in self._watchlist_or_load().entries}
        scored: list[ScoredName] = []
        scores: dict[str, float] = {}
        for ticker, cards in cards_by_ticker.items():
            _, best_card = max(
                cards, key=lambda sc: (_ACTION_RANK.get(sc[1].action, -1), sc[1].score)
            )
            deep = deep_by_ticker[ticker]
            cs = scoring.composite_score(
                scoring.CompositeInputs(
                    scorecard=best_card,
                    regime_label=regime_label,
                    accumulation=deep.accumulation,
                    stage=deep.stage,
                    crowding=deep.crowding,
                    capex_exposure=capex_of.get(ticker),
                )
            )
            scores[ticker] = cs.score
            rs = bm.relative_strength_all(df_by_ticker[ticker], benchmarks)
            rs_value = (sum(r.delta for r in rs) / len(rs)) if rs else None
            scored.append(ScoredName(ticker=ticker, score=cs.score, rs_value=rs_value))

        ranked = ranking.rank_opportunities(scored)
        allocation = ranking.suggest_allocation(ranked)
        if bar_date is not None:
            for ro in ranked:
                self.store.upsert_daily_score(
                    ticker=ro.ticker, date=bar_date, score=ro.score, rank=ro.rank,
                    n=ro.n, rs_percentile=ro.rs_percentile or 0.0,
                )
        return scores, ranked, allocation

    def _layers_and_thesis(
        self,
        signals: list[Signal],
        price_map: dict[str, pd.DataFrame],
        bar_date: Date | None,
    ) -> tuple[dict[str, float], dict[str, float], ThesisHealth]:
        """Layer-strength scores, the rotation delta vs the prior cycle, and thesis health."""
        wl = self._watchlist_or_load()
        strength = market.layer_strength(signals, wl)
        prior = self.store.prior_layer_strength(bar_date) if bar_date is not None else {}
        rotation = market.layer_rotation(strength, prior)
        if bar_date is not None:
            for layer, val in strength.items():
                self.store.upsert_layer_strength(date=bar_date, layer=layer, strength=val)

        above_50: dict[str, bool | None] = {}
        for leader in settings.thesis_leaders:
            df = price_map.get(leader)
            if df is None:
                continue
            m = _safe_call(compute_metrics, df, label="thesis_metrics", default=None)
            above_50[leader] = None if m is None else m.above_50_ema
        thesis = market.thesis_health(above_50)
        return strength, rotation, thesis

    def _portfolio_step(
        self,
        result: CycleResult,
        ranked: list[RankedOpportunity],
        cards_by_ticker: dict[str, list[tuple[Signal, scorecard.Scorecard]]],
        df_by_ticker: dict[str, pd.DataFrame],
        price_map: dict[str, pd.DataFrame],
        regime: Regime,
        bar_date: Date,
    ) -> None:
        """Resolve the exposure dial, size a paper book, and record a snapshot.

        Paper-only: target weights and the diff are *suggestions*, never executed.
        The book is re-applied on the configured rebalance cadence; a NAV/VOO
        snapshot is recorded every cycle for the dashboard's index comparison.
        """
        # Exposure dial from the regime history (prior labels + today's), with hysteresis.
        history = self.store.recent_regime_labels(bar_date, settings.regime_confirm_days + 10)
        exp = exposure_mod.target_exposure([*history, regime.label])
        result.exposure = exp.exposure
        result.exposure_result = exp

        # Build sizing candidates from the cross-sectional ranking + grades.
        rank_by_ticker = {r.ticker: r for r in ranked}
        candidates: list[Candidate] = []
        for ticker, ro in rank_by_ticker.items():
            cards = cards_by_ticker.get(ticker)
            if not cards:
                continue
            best_sig, best_card = max(
                cards, key=lambda sc: (_ACTION_RANK.get(sc[1].action, -1), sc[1].score)
            )
            dq = gating.disqualifiers(best_sig, best_card, regime)
            m = _safe_call(compute_metrics, df_by_ticker[ticker], label="pf_metrics", default=None)
            above_50 = True if m is None or m.above_50_ema is None else m.above_50_ema
            candidates.append(
                Candidate(
                    ticker=ticker,
                    score=ro.score,
                    rank=ro.rank,
                    grade=best_card.action,
                    disqualified=bool(dq),
                    above_50_ema=above_50,
                )
            )

        prices = {t: float(df["close"].iloc[-1]) for t, df in price_map.items() if not df.empty}
        portfolio = self.store.load_portfolio()
        held = portfolio.current_weights(prices)
        plan: SizingPlan = sizing_mod.target_weights(candidates, exp.exposure, held)
        result.rebalance_suggestions = [a.summary() for a in plan.actions]

        # Re-apply the paper book only on the configured cadence (turnover discipline).
        if self._rebalance_due(bar_date):
            portfolio.apply_targets(plan.target_weights, prices)
            self.store.save_portfolio(portfolio)

        nav = portfolio.nav(prices)
        result.portfolio_nav = nav
        result.portfolio_weights = portfolio.current_weights(prices)
        bench = _safe_call(self.benchmark_price_provider, label="benchmark_price", default=None)
        self.store.upsert_portfolio_snapshot(
            date=bar_date,
            nav=nav,
            exposure=exp.exposure,
            regime=regime.label,
            weights=result.portfolio_weights,
            suggestions=result.rebalance_suggestions,
            benchmark_value=float(bench) if bench is not None else 0.0,
        )

    def _rebalance_due(self, bar_date: Date) -> bool:
        """True when enough calendar time has elapsed since the last snapshot."""
        spacing = {"daily": 1, "weekly": 7, "monthly": 28}.get(settings.rebalance_cadence, 7)
        last = self.store.latest_portfolio_snapshot()
        if last is None:
            return True
        return (bar_date - last.date).days >= spacing

    def _gate(
        self,
        sig: Signal,
        card: scorecard.Scorecard | None,
        regime: Regime,
        decision: tuple[str, str] | None,
    ) -> tuple[list[str], bool]:
        """Run a would-be alert through the regime gate / disqualifiers.

        Returns ``(tripped_rules, suppressed)``. Only buy-style alerts with a
        scorecard are gated; warnings/breakdowns pass through untouched.
        """
        if not (settings.enable_regime_gate and decision and card is not None):
            return [], False
        severity = decision[0]
        dq = gating.disqualifiers(sig, card, regime)
        # In RISK_OFF, raise the bar for fresh buys (and discount aggressive ones).
        if regime.is_risk_off and severity == "entry" and sig.confidence < settings.risk_off_min_stars:
            dq = [*dq, f"RISK_OFF: confidence below the {settings.risk_off_min_stars}-star bar"]
        suppressed = bool(dq) and settings.disqualifier_mode == "suppress"
        return dq, suppressed

    def _score(
        self,
        ev: _Evaluated,
        ctx_market: market.MarketContext,
        benchmarks: dict[str, pd.DataFrame],
        layer_of: dict[str, str],
        earnings_cache: dict[str, int | None],
        beat_cache: dict[str, str | None],
    ) -> scorecard.Scorecard:
        t = ev.ticker
        if t not in earnings_cache:
            earnings_cache[t] = _safe_call(self.earnings_provider, t, label="earnings", default=None)
        if t not in beat_cache:
            beat_cache[t] = _safe_call(self.earnings_beat_provider, t, label="earnings_beat", default=None)
        hist = _safe_call(
            self.historical_provider, t, ev.strategy.name, ev.signal.status,
            label="historical", default=None,
        )
        ctx = ScoreContext(
            benchmarks=benchmarks,
            earnings_days=earnings_cache[t],
            breadth=ctx_market.breadth,
            leading_layers=ctx_market.leading_layers,
            ticker_layer=layer_of.get(t),
            historical=hist,
            earnings_beat=beat_cache[t],
        )
        return scorecard.build_scorecard(ev.signal, ev.df, ctx)

    def _catalysts(
        self,
        ticker: str,
        beat_cache: dict[str, str | None],
        news_cache: dict[str, list[dict[str, Any]]],
    ) -> dict[str, Any]:
        """Earnings beat/miss + recent headlines (context) for storage/dashboard."""
        if ticker not in news_cache:
            news_cache[ticker] = _safe_call(self.news_provider, ticker, label="news", default=[])
        headlines = [
            {
                "title": h.get("title", ""),
                "publisher": h.get("publisher", ""),
                "published": h["published"].isoformat() if h.get("published") else "",
                "link": h.get("link", ""),
            }
            for h in news_cache[ticker]
        ]
        return {"beat": beat_cache.get(ticker), "headlines": headlines}

    @staticmethod
    def _safe_evaluate(strat: Strategy, ticker: str, df: pd.DataFrame) -> Signal | None:
        """Evaluate one strategy, swallowing per-ticker errors so one bad symbol
        never aborts the whole cycle."""
        try:
            return strat.evaluate(ticker, df)
        except Exception as exc:  # noqa: BLE001 - resilience boundary, logged with context
            logger.exception("strategy {} failed on {}: {}", strat.name, ticker, exc)
            return None
