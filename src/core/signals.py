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

from dataclasses import dataclass, field
from datetime import date as Date
from typing import Any

import pandas as pd
from loguru import logger

from src.core.config import settings
from src.core.storage import Storage
from src.core.strategies.ath_pullback import ATHPullbackStrategy
from src.core.strategies.base import NO_SIGNAL, Signal, Strategy
from src.core.strategies.consolidation_breakout import ConsolidationBreakoutStrategy
from src.core.strategies.ema_pullback import EMAPullbackStrategy
from src.core.strategies.ipo_base import IPOBaseStrategy

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


@dataclass
class CycleResult:
    bar_date: Date | None = None
    n_tickers: int = 0
    n_signals: int = 0
    status_counts: dict[str, int] = field(default_factory=dict)
    alerts: list[Alert] = field(default_factory=list)


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


class SignalEngine:
    """Runs all strategies over a price map and reconciles signals/alerts with the DB."""

    def __init__(self, store: Storage, strategies: tuple[type[Strategy], ...] | None = None) -> None:
        self.store = store
        self.strategies: list[Strategy] = [cls() for cls in (strategies or DEFAULT_STRATEGIES)]

    def run_cycle(self, price_map: dict[str, pd.DataFrame]) -> CycleResult:
        result = CycleResult(n_tickers=len(price_map))

        for ticker, df in price_map.items():
            for strat in self.strategies:
                sig = self._safe_evaluate(strat, ticker, df)
                if sig is None or sig.status == NO_SIGNAL or sig.date is None:
                    continue

                prev = self.store.latest_signal(ticker, strat.name)
                prev_status = prev.status if prev else None

                self.store.record_signal(
                    ticker=sig.ticker,
                    date=sig.date,
                    strategy=strat.name,
                    status=sig.status,
                    details=sig.details,
                    confidence=sig.confidence,
                    patterns=sig.patterns_detected,
                )
                result.n_signals += 1
                result.bar_date = sig.date
                result.status_counts[sig.status] = result.status_counts.get(sig.status, 0) + 1

                decision = alert_decision(sig)
                if decision and prev_status != sig.status:
                    severity, message = decision
                    self.store.record_alert(
                        ticker=sig.ticker,
                        date=sig.date,
                        strategy=strat.name,
                        status=sig.status,
                        message=message,
                        confidence=sig.confidence,
                        patterns=sig.patterns_detected,
                    )
                    result.alerts.append(
                        Alert(
                            ticker=sig.ticker,
                            strategy=strat.name,
                            status=sig.status,
                            severity=severity,
                            message=message,
                            confidence=sig.confidence,
                            patterns=list(sig.patterns_detected),
                            date=sig.date,
                        )
                    )

        result.alerts.sort(key=lambda a: (-a.confidence, _SEVERITY_RANK.get(a.severity, 9)))
        return result

    @staticmethod
    def _safe_evaluate(strat: Strategy, ticker: str, df: pd.DataFrame) -> Signal | None:
        """Evaluate one strategy, swallowing per-ticker errors so one bad symbol
        never aborts the whole cycle."""
        try:
            return strat.evaluate(ticker, df)
        except Exception as exc:  # noqa: BLE001 - resilience boundary, logged with context
            logger.exception("strategy {} failed on {}: {}", strat.name, ticker, exc)
            return None
