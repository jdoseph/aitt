"""Trade Due Diligence Dossier (Session 9).

The scorecard grades a setup's *quality*; the dossier turns that into a
*decision aid* and guards against confirmation bias. Its anchor is the single
most important question — **"why should I NOT buy this right now?"** — so the
bear case sits next to the bull case and is never empty on a graded setup.

Every scorecard ``pass`` becomes a reason to buy; every ``warn``/``fail`` a
reason not to buy. The dossier adds its own dimensions (strategy confluence,
extension, 50/200-EMA trend alignment, market regime) and a concrete trade plan.
The position plan (sizing tier, add levels, profit targets) is **informational
only — never automated**. Pure/deterministic given its inputs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from src.core import benchmarks as bm
from src.core import levels
from src.core import market
from src.core import multitimeframe as mtf
from src.core.accumulation import AccumulationResult
from src.core.config import settings
from src.core.indicators import Metrics, compute_metrics
from src.core.scorecard import FAIL, PASS, WARN, Check, Scorecard
from src.core.stage import StageResult
from src.core.strategies.base import Signal

# Grade → suggested position-sizing tier (suggestion only, never executed).
SIZING_BY_ACTION: dict[str, str] = {
    "HIGH-QUALITY": "FULL",
    "DECENT": "HALF",
    "MARGINAL": "STARTER",
    "AVOID": "NONE",
}

# Short labels for the confluence line.
_STRAT_SHORT = {
    "ema_pullback": "EMA",
    "ath_pullback": "ATH",
    "consolidation_breakout": "FLAG",
    "ipo_base": "IPO",
}

# Lower = more important when picking the single strongest bull/bear factor and
# when capping the reason lists.
_PRIORITY = {
    "trend": 0,
    "trend_200": 1,
    "stage": 2,
    "rel_strength": 3,
    "risk_reward": 4,
    "resistance": 5,
    "extension": 6,
    "crowding": 7,
    "weekly": 8,
    "accumulation": 9,
    "confluence": 10,
    "historical": 11,
    "regime": 12,
    "breadth": 13,
    "volume": 14,
    "earnings": 15,
    "layer": 16,
    "catalyst": 17,
}

# How each scorecard check reads as a bull (pass) / bear (warn|fail) reason.
# value is interpolated from the check's own computed value string.
_BULL_PHRASE = {
    "trend": "Above the 50 EMA",
    "volume": "Volume {v}",
    "rel_strength": "Outperforming the market ({v})",
    "resistance": "Room to resistance ({v})",
    "risk_reward": "Favorable risk/reward ({v})",
    "layer": "In a leading value-chain layer",
    "breadth": "AI breadth healthy ({v})",
    "historical": "Historical edge {v}",
    "catalyst": "Beat last earnings",
}
_BEAR_PHRASE = {
    "trend": "Below the 50 EMA (downtrend risk)",
    "volume": "Volume below average ({v})",
    "earnings": "Earnings near ({v})",
    "rel_strength": "Lagging the market ({v})",
    "resistance": "Little headroom to resistance ({v})",
    "risk_reward": "Poor risk/reward ({v})",
    "layer": "Not in a leading layer",
    "breadth": "AI breadth cautious ({v})",
    "historical": "Weak historical edge ({v})",
    "catalyst": "Missed last earnings",
}

# Catalysts with no free structured feed — surfaced as a manual reminder.
_MANUAL_CHECKS = [
    "product launch / keynote",
    "investor day or analyst meeting",
    "IPO lockup expiration",
    "regulatory or export-control decision",
]


@dataclass(frozen=True)
class TradePlan:
    entry: float
    stop: float
    invalidation: str
    target: float | None
    risk_reward: float | None
    sizing_tier: str  # FULL | HALF | STARTER | NONE (suggestion only)
    profit_targets: list[float]

    def to_summary(self) -> dict[str, Any]:
        return {
            "entry": round(self.entry, 2),
            "stop": round(self.stop, 2),
            "invalidation": self.invalidation,
            "target": None if self.target is None else round(self.target, 2),
            "risk_reward": None if self.risk_reward is None else round(self.risk_reward, 2),
            "sizing_tier": self.sizing_tier,
            "profit_targets": [round(p, 2) for p in self.profit_targets],
        }


@dataclass(frozen=True)
class Dossier:
    ticker: str
    grade: str
    reasons_to_buy: list[str]
    reasons_not_to_buy: list[str]
    strongest_bull: str | None
    strongest_bear: str | None
    confluence: int
    confluence_detail: str
    extension: str
    trend_alignment: str
    market_regime: str
    trade_plan: TradePlan
    manual_catalyst_checks: list[str] = field(default_factory=list)

    def top_bear(self, n: int | None = None) -> list[str]:
        n = settings.dossier_bear_in_alert if n is None else n
        return self.reasons_not_to_buy[:n]

    def to_summary(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "grade": self.grade,
            "reasons_to_buy": self.reasons_to_buy,
            "reasons_not_to_buy": self.reasons_not_to_buy,
            "strongest_bull": self.strongest_bull,
            "strongest_bear": self.strongest_bear,
            "confluence": self.confluence,
            "confluence_detail": self.confluence_detail,
            "extension": self.extension,
            "trend_alignment": self.trend_alignment,
            "market_regime": self.market_regime,
            "trade_plan": self.trade_plan.to_summary(),
            "manual_catalyst_checks": self.manual_catalyst_checks,
        }


@dataclass
class DossierContext:
    """Everything :func:`build_dossier` needs beyond the signals + scorecard."""

    df: pd.DataFrame
    benchmarks: dict[str, pd.DataFrame] = field(default_factory=dict)
    best_signal: Signal | None = None  # drives the trade plan's stop type
    # Session 12 deeper signals (None => that dimension is simply omitted).
    stage: StageResult | None = None
    weekly: mtf.WeeklyTrend | None = None
    accumulation: AccumulationResult | None = None


# Grades, worst -> best, for the Stage-4 grade cap.
_GRADE_ORDER = ["AVOID", "MARGINAL", "DECENT", "HIGH-QUALITY"]


def _cap_grade(grade: str, ceiling: str) -> str:
    if grade not in _GRADE_ORDER or ceiling not in _GRADE_ORDER:
        return grade
    return grade if _GRADE_ORDER.index(grade) <= _GRADE_ORDER.index(ceiling) else ceiling


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _phrase(template: str, value: str) -> str:
    return template.format(v=value) if "{v}" in template else template


def _scorecard_reasons(card: Scorecard) -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    """Split graded checks into (bull, bear) priority/text tuples. NA is skipped."""
    bull: list[tuple[int, str]] = []
    bear: list[tuple[int, str]] = []
    for c in card.checks:
        pri = _PRIORITY.get(c.name, 50)
        if c.status == PASS and c.name in _BULL_PHRASE:
            bull.append((pri, _phrase(_BULL_PHRASE[c.name], c.value)))
        elif c.status in (WARN, FAIL) and c.name in _BEAR_PHRASE:
            bear.append((pri, _phrase(_BEAR_PHRASE[c.name], c.value)))
    return bull, bear


def _confluence(signals: list[Signal]) -> tuple[int, str]:
    """Count distinct strategies with a bullish-leaning status + a readable detail."""
    aligned = [s for s in signals if s.status in market.BULLISH_STATUSES]
    by_strat: dict[str, str] = {}
    for s in aligned:  # keep the first status seen per strategy
        by_strat.setdefault(s.strategy_name, s.status)
    detail = " + ".join(f"{_STRAT_SHORT.get(k, k)} {v}" for k, v in by_strat.items())
    return len(by_strat), detail


def _extension_text(m: Metrics) -> str:
    parts = []
    if m.dist_ema_21_pct is not None:
        parts.append(f"{m.dist_ema_21_pct:+.1f}% vs 21 EMA")
    if m.dist_ema_50_pct is not None:
        parts.append(f"{m.dist_ema_50_pct:+.1f}% vs 50 EMA")
    return " · ".join(parts) if parts else "n/a"


def _trend_alignment_text(m: Metrics) -> str:
    a50, a200 = m.above_50_ema, m.above_200_ema
    if a50 is None and a200 is None:
        return "n/a (thin history)"
    if a50 and a200:
        return "above the 50 & 200 EMA (full alignment)"
    if a50 and a200 is False:
        return "above the 50 EMA, below the 200 EMA"
    if a50 is False and a200:
        return "below the 50 EMA, above the 200 EMA"
    if a50 is False and a200 is False:
        return "below the 50 & 200 EMA (no alignment)"
    # One side unknown.
    known = "above" if (a50 or a200) else "below"
    return f"{known} its available long-term EMA"


def _resistance_target(df: pd.DataFrame, m: Metrics) -> float | None:
    res = levels.nearest_resistance(df, m.close)
    if res is not None:
        return res
    return m.ath if m.ath > m.close else None


def _ordered(reasons: list[tuple[int, str]]) -> list[str]:
    """Sort by priority, drop duplicates, cap at the configured max."""
    seen: set[str] = set()
    out: list[str] = []
    for _, text in sorted(reasons, key=lambda t: t[0]):
        if text not in seen:
            seen.add(text)
            out.append(text)
    return out[: settings.dossier_max_reasons]


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #
def build_dossier(
    ticker: str, signals: list[Signal], card: Scorecard, ctx: DossierContext
) -> Dossier:
    """Assemble the bull/bear case + trade plan for one candidate ticker."""
    m = compute_metrics(ctx.df)
    best = ctx.best_signal or (signals[0] if signals else None)

    bull, bear = _scorecard_reasons(card)

    # --- dossier-specific dimensions ---
    confluence, confl_detail = _confluence(signals)
    if confluence >= 2:
        bull.append((_PRIORITY["confluence"], f"{confluence}/4 strategies aligned ({confl_detail})"))

    if m.dist_ema_50_pct is not None:
        if m.dist_ema_50_pct > settings.ema_chasing_pct:
            bear.append(
                (_PRIORITY["extension"], f"{m.dist_ema_50_pct:.0f}% above the 50 EMA (extended/chasing)")
            )
        elif m.dist_ema_50_pct >= 0:
            bull.append(
                (_PRIORITY["extension"], f"Not overextended ({m.dist_ema_50_pct:+.1f}% over 50 EMA)")
            )

    if m.above_200_ema is True:
        bull.append((_PRIORITY["trend_200"], "Above the 200 EMA (long-term uptrend)"))
    elif m.above_200_ema is False:
        bear.append((_PRIORITY["trend_200"], "Below the 200 EMA (long-term trend down)"))

    regime = bm.market_regime(ctx.benchmarks)
    regime_text = regime.summary()
    if regime.flags:
        if regime.supportive:
            bull.append((_PRIORITY["regime"], f"Market regime supportive ({regime_text})"))
        else:
            bear.append((_PRIORITY["regime"], f"Market regime weak ({regime_text})"))

    # --- Session 12: deeper signals (stage / weekly / crowding / accumulation) ---
    grade = card.action

    if m.crowding is not None and m.crowding >= settings.crowding_high_score:
        bear.append((_PRIORITY["crowding"], f"Crowded / extended (crowding {m.crowding:.0f}/100)"))

    if ctx.stage is not None and ctx.stage.stage:
        if ctx.stage.is_advancing:
            bull.append((_PRIORITY["stage"], "Stage 2 (advancing) — buyable trend"))
        elif ctx.stage.is_declining:
            bear.append((_PRIORITY["stage"], "Stage 4 (declining) — falling-knife risk"))
            grade = _cap_grade(grade, "MARGINAL")  # a dip in a downtrend isn't a dip
        elif ctx.stage.stage == 3:
            bear.append((_PRIORITY["stage"], "Stage 3 (topping) — momentum stalling"))

    if ctx.weekly is not None:
        if ctx.weekly.trend == mtf.UPTREND:
            bull.append((_PRIORITY["weekly"], "Weekly uptrend (higher-timeframe aligned)"))
        elif ctx.weekly.trend == mtf.DOWNTREND:
            bear.append((_PRIORITY["weekly"], "Weekly downtrend (counter-trend setup)"))

    if ctx.accumulation is not None:
        acc = ctx.accumulation
        if acc.label == "accumulation":
            bull.append((_PRIORITY["accumulation"], f"Institutional accumulation (score {acc.score:.0f})"))
        elif acc.label == "distribution":
            bear.append((_PRIORITY["accumulation"], f"Distribution — sellers in control (score {acc.score:.0f})"))

    reasons_to_buy = _ordered(bull)
    reasons_not_to_buy = _ordered(bear)
    # The bear case is never empty on a graded setup — even a clean chart carries
    # the discipline reminder that nothing here is risk-free.
    if not reasons_not_to_buy:
        reasons_not_to_buy = [
            "No glaring red flags — but confirm position size, your own thesis, and the manual catalysts below"
        ]

    # --- trade plan ---
    target = _resistance_target(ctx.df, m)
    stop = levels.strategy_stop(ctx.df, best, m) if best else levels.suggested_stop(ctx.df, m.close)
    plan = TradePlan(
        entry=m.close,
        stop=stop,
        invalidation=levels.invalidation_text(best) if best else "loss of the 50 EMA",
        target=target,
        risk_reward=levels.risk_reward(m.close, stop, target),
        sizing_tier=SIZING_BY_ACTION.get(grade, "NONE"),
        profit_targets=[round(m.close * (1 + p / 100), 2) for p in settings.profit_target_pcts],
    )

    return Dossier(
        ticker=ticker,
        grade=grade,
        reasons_to_buy=reasons_to_buy,
        reasons_not_to_buy=reasons_not_to_buy,
        strongest_bull=reasons_to_buy[0] if reasons_to_buy else None,
        strongest_bear=reasons_not_to_buy[0] if reasons_not_to_buy else None,
        confluence=confluence,
        confluence_detail=confl_detail,
        extension=_extension_text(m),
        trend_alignment=_trend_alignment_text(m),
        market_regime=regime_text,
        trade_plan=plan,
        manual_catalyst_checks=list(_MANUAL_CHECKS),
    )
