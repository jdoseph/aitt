"""Composite 0-100 setup score (Session 11).

Where the Session 7 scorecard grades a setup in isolation (pass/warn/fail →
HIGH-QUALITY…AVOID), the **composite score** rolls everything into a single
0-100 number so names can be ranked against each other (see :mod:`ranking`).

It maps the existing scorecard checks plus the Session 12 deeper signals
(accumulation, Weinstein stage, crowding) and the market regime into seven
weighted categories:

    Technical 30 · Relative-strength 20 · Volume-Accumulation 15 ·
    Market-regime 10 · Earnings 10 · Value-chain leadership 10 · Catalyst 5

A category with no data is dropped and the remaining weights are renormalized,
so the composite degrades gracefully rather than punishing missing inputs.
Pure/deterministic given its inputs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.core.accumulation import AccumulationResult
from src.core.config import settings
from src.core.regime import NEUTRAL, RISK_OFF, RISK_ON
from src.core.scorecard import FAIL, PASS, WARN, Scorecard
from src.core.stage import StageResult

_STATUS_VALUE = {PASS: 1.0, WARN: 0.5, FAIL: 0.0}

# Category keys (stable identifiers used in subscore dicts / storage).
TECHNICAL = "technical"
REL_STRENGTH = "rel_strength"
VOLUME_ACCUM = "volume_accum"
REGIME = "regime"
EARNINGS = "earnings"
LAYER = "layer"
CATALYST = "catalyst"

CATEGORY_TITLES: dict[str, str] = {
    TECHNICAL: "Technical",
    REL_STRENGTH: "Relative strength",
    VOLUME_ACCUM: "Volume / accumulation",
    REGIME: "Market regime",
    EARNINGS: "Earnings",
    LAYER: "Value-chain leadership",
    CATALYST: "Catalyst",
}


def _weight(category: str) -> float:
    return {
        TECHNICAL: settings.score_w_technical,
        REL_STRENGTH: settings.score_w_rel_strength,
        VOLUME_ACCUM: settings.score_w_volume_accum,
        REGIME: settings.score_w_regime,
        EARNINGS: settings.score_w_earnings,
        LAYER: settings.score_w_layer,
        CATALYST: settings.score_w_catalyst,
    }[category]


@dataclass
class CompositeInputs:
    """Everything the composite needs. Anything ``None`` simply drops its category."""

    scorecard: Scorecard | None = None
    regime_label: str | None = None  # RISK_ON | NEUTRAL | RISK_OFF
    accumulation: AccumulationResult | None = None
    stage: StageResult | None = None
    crowding: float | None = None  # 0-100 (higher = more extended)
    capex_exposure: int | None = None  # 0-100


@dataclass(frozen=True)
class CategoryScore:
    name: str
    subscore: float  # 0-100
    weight: float  # effective (renormalized) weight, 0-100
    contribution: float  # subscore * weight / 100 (contributions sum to the composite)
    detail: str = ""


@dataclass(frozen=True)
class CompositeScore:
    score: float  # 0-100
    categories: list[CategoryScore] = field(default_factory=list)

    def to_summary(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 1),
            "categories": [
                {
                    "name": c.name,
                    "subscore": round(c.subscore, 1),
                    "weight": round(c.weight, 1),
                    "contribution": round(c.contribution, 1),
                }
                for c in self.categories
            ],
        }


def _check_val(card: Scorecard | None, name: str) -> float | None:
    """Pass/warn/fail of a scorecard check as 1.0/0.5/0.0, or None if na/absent."""
    if card is None:
        return None
    for c in card.checks:
        if c.name == name:
            return _STATUS_VALUE.get(c.status)  # None for NA
    return None


def _mean(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else None


def _stage_factor(stage: StageResult | None) -> float | None:
    if stage is None or stage.stage == 0:
        return None
    return {2: 1.0, 1: 0.5, 3: 0.4, 4: 0.0}.get(stage.stage)


def _technical(inp: CompositeInputs) -> float | None:
    """Trend / R:R / headroom, blended with stage and a crowding penalty (0-100)."""
    base = _mean(
        [
            _check_val(inp.scorecard, "trend"),
            _check_val(inp.scorecard, "risk_reward"),
            _check_val(inp.scorecard, "resistance"),
        ]
    )
    stage_f = _stage_factor(inp.stage)
    crowd_f = None if inp.crowding is None else 1.0 - min(1.0, inp.crowding / 100.0)
    blended = _mean([v for v in (base, stage_f, crowd_f) if v is not None])
    return None if blended is None else blended * 100.0


def _rel_strength(inp: CompositeInputs) -> float | None:
    v = _check_val(inp.scorecard, "rel_strength")
    return None if v is None else v * 100.0


def _volume_accum(inp: CompositeInputs) -> float | None:
    vol = _check_val(inp.scorecard, "volume")
    acc = None if inp.accumulation is None else inp.accumulation.score / 100.0
    blended = _mean([v for v in (vol, acc) if v is not None])
    return None if blended is None else blended * 100.0


def _regime(inp: CompositeInputs) -> float | None:
    return {RISK_ON: 100.0, NEUTRAL: 50.0, RISK_OFF: 0.0}.get(inp.regime_label or "")


def _earnings(inp: CompositeInputs) -> float | None:
    v = _check_val(inp.scorecard, "earnings")
    return None if v is None else v * 100.0


def _layer(inp: CompositeInputs) -> float | None:
    """Layer leadership blended with the name's structural AI-capex exposure."""
    lead = _check_val(inp.scorecard, "layer")
    capex = None if inp.capex_exposure is None else inp.capex_exposure / 100.0
    blended = _mean([v for v in (lead, capex) if v is not None])
    return None if blended is None else blended * 100.0


def _catalyst(inp: CompositeInputs) -> float | None:
    """Earnings beat/miss + historical edge (evidence)."""
    blended = _mean(
        [_check_val(inp.scorecard, "catalyst"), _check_val(inp.scorecard, "historical")]
    )
    return None if blended is None else blended * 100.0


_CATEGORY_FNS = [
    (TECHNICAL, _technical),
    (REL_STRENGTH, _rel_strength),
    (VOLUME_ACCUM, _volume_accum),
    (REGIME, _regime),
    (EARNINGS, _earnings),
    (LAYER, _layer),
    (CATALYST, _catalyst),
]


def composite_score(inputs: CompositeInputs) -> CompositeScore:
    """Compute the weighted 0-100 composite. Absent categories renormalize out."""
    raw: list[tuple[str, float, float]] = []  # (name, subscore, nominal_weight)
    for name, fn in _CATEGORY_FNS:
        sub = fn(inputs)
        if sub is not None:
            raw.append((name, max(0.0, min(100.0, sub)), _weight(name)))

    total_w = sum(w for _, _, w in raw)
    categories: list[CategoryScore] = []
    score = 0.0
    for name, sub, w in raw:
        eff = (w / total_w * 100.0) if total_w else 0.0
        contrib = sub * eff / 100.0
        score += contrib
        categories.append(
            CategoryScore(name=name, subscore=sub, weight=eff, contribution=contrib)
        )
    return CompositeScore(score=score, categories=categories)
