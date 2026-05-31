"""Session 13: conviction sizing + concentration caps + RS rotation + bands.

`target_weights` turns ranked candidates + an exposure budget + current holdings
into target weights and a list of rebalance *suggestions* (paper-only). Pure and
deterministic.
"""

from __future__ import annotations

import pytest

from src.core import sizing
from src.core.sizing import Candidate


def _candidates(scores: dict[str, float], **overrides: object) -> list[Candidate]:
    """Build candidates ranked by score desc (rank 1 = highest score)."""
    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    out = []
    for i, (ticker, score) in enumerate(ordered):
        out.append(
            Candidate(
                ticker=ticker,
                score=score,
                rank=i + 1,
                grade=str(overrides.get("grade", "DECENT")),
                disqualified=bool(overrides.get("disqualified", False)),
                above_50_ema=bool(overrides.get("above_50_ema", True)),
            )
        )
    return out


# --- conviction sizing (fresh book) ---------------------------------------- #
def test_top_n_selected_weights_sum_to_exposure() -> None:
    cands = _candidates({"A": 90, "B": 80, "C": 70, "D": 60, "E": 50, "F": 40, "G": 30, "H": 20})
    plan = sizing.target_weights(cands, exposure=1.0, held={}, max_positions=6)
    assert set(plan.target_weights) == {"A", "B", "C", "D", "E", "F"}  # top 6 only
    assert sum(plan.target_weights.values()) == pytest.approx(1.0)
    # Weights are proportional to score: A (highest) outweighs F (lowest).
    assert plan.target_weights["A"] > plan.target_weights["F"]


def test_partial_exposure_scales_the_book() -> None:
    # Cap raised above the per-name share so the budget isn't clipped (with only
    # two names the default 25% cap would bind at 50%, leaving residual cash).
    cands = _candidates({"A": 60, "B": 40})
    plan = sizing.target_weights(
        cands, exposure=0.6, held={}, max_positions=6, max_position_pct=0.5
    )
    assert sum(plan.target_weights.values()) == pytest.approx(0.6)


def test_concentration_cap_leaves_residual_cash() -> None:
    # Two names, 25% cap → only 50% can be invested even at 100% exposure target.
    cands = _candidates({"A": 60, "B": 40})
    plan = sizing.target_weights(
        cands, exposure=1.0, held={}, max_positions=6, max_position_pct=0.25
    )
    assert sum(plan.target_weights.values()) == pytest.approx(0.5)  # rest stays in cash


def test_concentration_cap_holds() -> None:
    # A dominates — its proportional weight would exceed the 25% cap and must be clipped.
    cands = _candidates({"A": 200, "B": 50, "C": 50, "D": 50, "E": 50})
    plan = sizing.target_weights(
        cands, exposure=1.0, held={}, max_positions=6, max_position_pct=0.25
    )
    assert plan.target_weights["A"] == pytest.approx(0.25)
    assert all(w <= 0.25 + 1e-9 for w in plan.target_weights.values())
    assert sum(plan.target_weights.values()) == pytest.approx(1.0)


def test_dust_positions_below_floor_are_dropped() -> None:
    cands = _candidates({"A": 100, "B": 100, "C": 100, "D": 100, "E": 100, "F": 1})
    plan = sizing.target_weights(
        cands, exposure=1.0, held={}, max_positions=6, min_position_pct=0.05
    )
    assert "F" not in plan.target_weights  # ~0.2% weight is dust → dropped
    assert sum(plan.target_weights.values()) == pytest.approx(1.0)


def test_disqualified_and_low_grade_names_are_not_entered() -> None:
    cands = [
        Candidate("A", 90, 1, "DECENT"),
        Candidate("B", 80, 2, "DECENT", disqualified=True),
        Candidate("C", 70, 3, "AVOID"),  # below min_grade
        Candidate("D", 60, 4, "HIGH-QUALITY"),
    ]
    plan = sizing.target_weights(cands, exposure=1.0, held={}, max_positions=6, min_grade="DECENT")
    assert set(plan.target_weights) == {"A", "D"}


# --- RS rotation (held names) ---------------------------------------------- #
def test_held_name_past_exit_rank_is_exited() -> None:
    # H is held but has fallen to rank 12 (> exit_rank 10) → EXIT.
    cands = _candidates({f"T{i}": 100 - i for i in range(14)})  # T0..T13, ranks 1..14
    held = {"T11": 0.15}  # T11 has rank 12
    plan = sizing.target_weights(cands, exposure=1.0, held=held, max_positions=6, exit_rank=10)
    exits = [a for a in plan.actions if a.action == "EXIT"]
    assert any(a.ticker == "T11" for a in exits)
    assert plan.target_weights.get("T11", 0.0) == 0.0


def test_held_name_losing_50ema_is_exited() -> None:
    cands = [
        Candidate("A", 90, 1, "DECENT"),
        Candidate("B", 80, 2, "DECENT", above_50_ema=False),  # held, lost its 50 EMA
    ]
    plan = sizing.target_weights(
        cands, exposure=1.0, held={"B": 0.2}, max_positions=6, exit_rank=10
    )
    assert any(a.ticker == "B" and a.action == "EXIT" for a in plan.actions)


def test_held_name_in_hold_band_is_kept_not_cut() -> None:
    # max_positions=2, exit_rank=10. C is held at rank 3 (in the hold band 3..10).
    cands = _candidates({"A": 90, "B": 80, "C": 70, "D": 60})
    plan = sizing.target_weights(
        cands, exposure=1.0, held={"C": 0.2}, max_positions=2, exit_rank=10
    )
    assert "C" in plan.target_weights and plan.target_weights["C"] == pytest.approx(0.2)
    assert not any(a.ticker == "C" and a.action == "EXIT" for a in plan.actions)


# --- no-trade band --------------------------------------------------------- #
def test_no_trade_band_suppresses_tiny_drift() -> None:
    # Single name whose ideal weight (1.0) is ~equal to its current weight.
    cands = _candidates({"A": 100})
    plan = sizing.target_weights(
        cands, exposure=1.0, held={"A": 0.99}, max_positions=6,
        max_position_pct=1.0, rebalance_threshold_pct=0.03,
    )
    # Target ~1.0 vs current 0.99 → 1% drift (<3% band) → no ADD/TRIM suggestion.
    assert not any(a.ticker == "A" and a.action in ("ADD", "TRIM") for a in plan.actions)


def test_meaningful_drift_emits_a_suggestion() -> None:
    cands = _candidates({"A": 100})
    plan = sizing.target_weights(
        cands, exposure=1.0, held={"A": 0.5}, max_positions=6,
        max_position_pct=1.0, rebalance_threshold_pct=0.03,
    )
    # 50% → 100% target is well past the 3% band → an ADD suggestion fires.
    assert any(a.ticker == "A" and a.action == "ADD" for a in plan.actions)


def test_new_name_is_an_enter_action() -> None:
    cands = _candidates({"A": 100})
    plan = sizing.target_weights(cands, exposure=1.0, held={}, max_positions=6)
    assert any(a.ticker == "A" and a.action == "ENTER" for a in plan.actions)


def test_empty_candidates_returns_empty_plan() -> None:
    plan = sizing.target_weights([], exposure=1.0, held={}, max_positions=6)
    assert plan.target_weights == {}
    assert plan.actions == []
