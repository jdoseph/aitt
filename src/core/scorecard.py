"""Setup Quality Scorecard — checks 1-8 (Session 7).

Given a signal + price frame + a :class:`ScoreContext` (benchmarks, earnings days,
market breadth, leading layers), produce a :class:`Scorecard`: a list of pass/
warn/fail/na :class:`Check`s, a weighted score, and an action grade. Pure and
deterministic given its inputs — all network lives in the context providers.

Checks 9 (historical edge) and 10 (catalysts) are added in Session 8.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from src.core import benchmarks as bm
from src.core import levels
from src.core.config import settings
from src.core.indicators import compute_metrics
from src.core.market import Breadth
from src.core.strategies.base import Signal

PASS, WARN, FAIL, NA = "pass", "warn", "fail", "na"

# Display names + the order checks appear in the composite alert.
CHECK_TITLES: dict[str, str] = {
    "trend": "Trend",
    "volume": "Volume",
    "earnings": "Earnings",
    "rel_strength": "Rel. strength",
    "risk_reward": "Risk/Reward",
    "resistance": "Resistance",
    "layer": "Leading layer",
    "breadth": "AI breadth",
}

_ACTIONS = ["AVOID", "MARGINAL", "DECENT", "HIGH-QUALITY"]
_STATUS_VALUE = {PASS: 1.0, WARN: 0.5, FAIL: 0.0}
_WEIGHTS = {"trend": 2.0, "risk_reward": 2.0}  # everything else weighs 1.0


@dataclass(frozen=True)
class Check:
    name: str
    status: str  # pass | warn | fail | na
    value: str = ""
    detail: str = ""


@dataclass
class ScoreContext:
    benchmarks: dict[str, pd.DataFrame] = field(default_factory=dict)
    earnings_days: int | None = None
    breadth: Breadth | None = None
    leading_layers: frozenset[str] = frozenset()
    ticker_layer: str | None = None


@dataclass(frozen=True)
class Scorecard:
    checks: list[Check]
    score: float
    action: str

    def to_summary(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "score": round(self.score, 3),
            "checks": [{"name": c.name, "status": c.status, "value": c.value} for c in self.checks],
        }

    def render_lines(self) -> list[str]:
        glyph = {PASS: "✅", WARN: "⚠️", FAIL: "❌", NA: "•"}
        lines = [
            f"{CHECK_TITLES.get(c.name, c.name)}: {c.value} {glyph.get(c.status, '')}".rstrip()
            for c in self.checks
        ]
        lines.append(f"Action: {self.action}")
        return lines


# --------------------------------------------------------------------------- #
# Individual checks
# --------------------------------------------------------------------------- #
def _check_trend(m: Any) -> Check:
    if m.ema_50 is None:
        return Check("trend", NA, "n/a (thin history)")
    if m.close > m.ema_50:
        return Check("trend", PASS, "above 50 EMA")
    return Check("trend", FAIL, "below 50 EMA")


def _check_volume(m: Any) -> Check:
    vr = m.vol_ratio
    value = f"{vr:.1f}x avg"
    if vr >= settings.breakout_volume_mult:
        return Check("volume", PASS, value)
    if vr >= 1.0:
        return Check("volume", WARN, value)
    return Check("volume", FAIL, value)


def _check_earnings(days: int | None) -> Check:
    if days is None:
        return Check("earnings", NA, "unknown")
    value = f"{days}d away"
    if days < settings.earnings_buffer_days:
        return Check("earnings", WARN, value, "inside earnings buffer")
    return Check("earnings", PASS, value)


def _check_rel_strength(df: pd.DataFrame, benches: dict[str, pd.DataFrame]) -> Check:
    rs = bm.relative_strength_all(df, benches)
    if not rs:
        return Check("rel_strength", NA, "n/a")
    beats = sum(1 for r in rs if r.outperform)
    avg_delta = sum(r.delta for r in rs) / len(rs)
    value = f"{avg_delta:+.1f}% vs mkt ({beats}/{len(rs)})"
    if beats >= math.ceil(len(rs) / 2):
        return Check("rel_strength", PASS, value)
    return Check("rel_strength", FAIL, value)


def _resistance_target(df: pd.DataFrame, m: Any) -> float | None:
    res = levels.nearest_resistance(df, m.close)
    if res is not None:
        return res
    return m.ath if m.ath > m.close else None


def _check_resistance(df: pd.DataFrame, m: Any, target: float | None) -> Check:
    if target is None:
        return Check("resistance", PASS, "blue sky (no overhead)")
    headroom = (target - m.close) / m.close * 100
    value = f"{target:.2f} (+{headroom:.1f}%)"
    if headroom < settings.low_headroom_pct:
        return Check("resistance", WARN, value, "little room to run")
    return Check("resistance", PASS, value)


def _check_risk_reward(df: pd.DataFrame, m: Any, target: float | None) -> Check:
    stop = levels.suggested_stop(df, m.close)
    rr = levels.risk_reward(m.close, stop, target)
    if rr is None:
        return Check("risk_reward", NA, "n/a")
    value = f"{rr:.1f} : 1"
    if rr >= settings.min_risk_reward:
        return Check("risk_reward", PASS, value, f"stop ~{stop:.2f}")
    if rr >= 1.0:
        return Check("risk_reward", WARN, value, f"stop ~{stop:.2f}")
    return Check("risk_reward", FAIL, value, f"stop ~{stop:.2f}")


def _check_layer(layer: str | None, leading: frozenset[str]) -> Check:
    if layer is None or not leading:
        return Check("layer", NA, "n/a")
    if layer in leading:
        return Check("layer", PASS, "in a leading layer")
    return Check("layer", WARN, "not a leading layer")


def _check_breadth(breadth: Breadth | None) -> Check:
    if breadth is None:
        return Check("breadth", NA, "n/a")
    value = breadth.summary()
    return Check("breadth", PASS, value) if breadth.healthy else Check("breadth", WARN, value)


# --------------------------------------------------------------------------- #
# Assembly + grading
# --------------------------------------------------------------------------- #
def _grade(checks: list[Check]) -> tuple[float, str]:
    num = den = 0.0
    for c in checks:
        if c.status == NA:
            continue
        w = _WEIGHTS.get(c.name, 1.0)
        num += w * _STATUS_VALUE[c.status]
        den += w
    score = (num / den) if den else 0.0

    if score >= 0.8:
        action = "HIGH-QUALITY"
    elif score >= 0.6:
        action = "DECENT"
    elif score >= 0.4:
        action = "MARGINAL"
    else:
        action = "AVOID"

    by_name = {c.name: c for c in checks}
    if by_name.get("trend") and by_name["trend"].status == FAIL:
        action = _min_action(action, "MARGINAL")  # below the 50 EMA caps quality
    if by_name.get("risk_reward") and by_name["risk_reward"].status == FAIL:
        action = _min_action(action, "DECENT")
    return score, action


def _min_action(a: str, b: str) -> str:
    return a if _ACTIONS.index(a) <= _ACTIONS.index(b) else b


def build_scorecard(signal: Signal, df: pd.DataFrame, ctx: ScoreContext) -> Scorecard:
    """Assemble checks 1-8 into a graded scorecard for an actionable signal."""
    m = compute_metrics(df)
    target = _resistance_target(df, m)
    checks = [
        _check_trend(m),
        _check_volume(m),
        _check_earnings(ctx.earnings_days),
        _check_rel_strength(df, ctx.benchmarks),
        _check_resistance(df, m, target),
        _check_risk_reward(df, m, target),
        _check_layer(ctx.ticker_layer, ctx.leading_layers),
        _check_breadth(ctx.breadth),
    ]
    score, action = _grade(checks)
    return Scorecard(checks=checks, score=score, action=action)
