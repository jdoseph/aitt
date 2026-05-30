"""Composite-score tests (Session 11)."""

from __future__ import annotations

import json

import pytest

from src.core import scoring
from src.core.accumulation import AccumulationResult
from src.core.regime import NEUTRAL, RISK_OFF, RISK_ON
from src.core.scorecard import FAIL, NA, PASS, WARN, Check, Scorecard
from src.core.stage import StageResult


def _card(**checks: str) -> Scorecard:
    """Build a scorecard from name=status kwargs."""
    return Scorecard(checks=[Check(n, st) for n, st in checks.items()], score=0.0, action="DECENT")


def _acc(score: float) -> AccumulationResult:
    return AccumulationResult(score, "neutral", True, True, 1.5, 0.7)


def test_score_in_range_and_contributions_sum() -> None:
    inp = scoring.CompositeInputs(
        scorecard=_card(
            trend=PASS, risk_reward=PASS, resistance=PASS, rel_strength=PASS,
            volume=PASS, earnings=PASS, layer=PASS, catalyst=PASS, historical=PASS,
        ),
        regime_label=RISK_ON,
        accumulation=_acc(80.0),
        stage=StageResult(2, "advancing", True, 3.0),
        crowding=10.0,
        capex_exposure=90,
    )
    cs = scoring.composite_score(inp)
    assert 0.0 <= cs.score <= 100.0
    assert cs.score > 80.0  # everything bullish
    assert sum(c.contribution for c in cs.categories) == pytest.approx(cs.score)
    assert all(0.0 <= c.subscore <= 100.0 for c in cs.categories)


def test_all_fail_scores_low() -> None:
    inp = scoring.CompositeInputs(
        scorecard=_card(
            trend=FAIL, risk_reward=FAIL, resistance=FAIL, rel_strength=FAIL,
            volume=FAIL, earnings=WARN, layer=WARN, catalyst=WARN, historical=FAIL,
        ),
        regime_label=RISK_OFF,
        accumulation=_acc(10.0),
        stage=StageResult(4, "declining", False, -3.0),
        crowding=95.0,
        capex_exposure=10,
    )
    cs = scoring.composite_score(inp)
    assert cs.score < 30.0


def test_na_category_renormalizes() -> None:
    # Only the regime category has data -> the composite equals the regime subscore.
    inp = scoring.CompositeInputs(regime_label=NEUTRAL)
    cs = scoring.composite_score(inp)
    assert len(cs.categories) == 1
    assert cs.categories[0].name == scoring.REGIME
    assert cs.score == pytest.approx(50.0)
    assert cs.categories[0].weight == pytest.approx(100.0)  # renormalized


def test_empty_inputs_score_zero() -> None:
    cs = scoring.composite_score(scoring.CompositeInputs())
    assert cs.score == 0.0
    assert cs.categories == []


def test_na_checks_drop_their_category() -> None:
    inp = scoring.CompositeInputs(scorecard=_card(rel_strength=NA), regime_label=RISK_ON)
    cs = scoring.composite_score(inp)
    names = {c.name for c in cs.categories}
    assert scoring.REL_STRENGTH not in names  # NA rel-strength contributes nothing
    assert scoring.REGIME in names


def test_summary_json_serializable() -> None:
    cs = scoring.composite_score(scoring.CompositeInputs(regime_label=RISK_ON))
    json.dumps(cs.to_summary())
