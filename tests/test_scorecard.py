"""Setup quality scorecard tests (Session 7)."""

from __future__ import annotations

from src.core import scorecard as sc
from src.core.market import Breadth
from src.core.scorecard import Check, ScoreContext, build_scorecard
from src.core.strategies.base import Signal
from tests.factories import make_ohlcv

SIG = Signal(ticker="T", strategy_name="ema_pullback", status="AT_21_EMA")


# --- grading logic (pure) -------------------------------------------------- #
def _checks(**status_by_name: str) -> list[Check]:
    return [Check(name, st) for name, st in status_by_name.items()]


def test_grade_all_pass_is_high_quality() -> None:
    score, action = sc._grade(_checks(trend="pass", volume="pass", risk_reward="pass"))
    assert score == 1.0
    assert action == "HIGH-QUALITY"


def test_trend_fail_caps_action_at_marginal() -> None:
    # Everything else passes, but below the 50 EMA caps the grade.
    _, action = sc._grade(
        _checks(trend="fail", volume="pass", rel_strength="pass", breadth="pass")
    )
    assert action == "MARGINAL"


def test_risk_reward_fail_caps_action_at_decent() -> None:
    _, action = sc._grade(
        _checks(trend="pass", volume="pass", risk_reward="fail", rel_strength="pass")
    )
    assert action == "DECENT"


def test_na_checks_are_excluded_from_score() -> None:
    score, _ = sc._grade(_checks(trend="pass", volume="na", earnings="na"))
    assert score == 1.0  # only the trend pass counts


# --- end-to-end ------------------------------------------------------------ #
def test_build_scorecard_uptrend_passes_trend() -> None:
    closes = [100.0 + i for i in range(60)]  # steady uptrend
    vols = [1_000_000.0] * 59 + [2_500_000.0]  # volume surge on the last bar
    df = make_ohlcv(closes, volumes=vols)
    card = build_scorecard(SIG, df, ScoreContext(breadth=Breadth(20, 10, 8, 38)))
    by = {c.name: c for c in card.checks}
    assert by["trend"].status == "pass"  # close well above the 50 EMA
    assert by["volume"].status == "pass"
    assert card.action in ("HIGH-QUALITY", "DECENT")


def test_build_scorecard_downtrend_fails_trend_and_caps() -> None:
    closes = [160.0 - i for i in range(60)]  # steady downtrend
    df = make_ohlcv(closes)
    card = build_scorecard(SIG, df, ScoreContext())
    by = {c.name: c for c in card.checks}
    assert by["trend"].status == "fail"
    assert card.action in ("AVOID", "MARGINAL")  # trend fail caps quality


def test_scorecard_serialization_and_render() -> None:
    df = make_ohlcv([100.0 + i for i in range(60)])
    card = build_scorecard(SIG, df, ScoreContext())
    summary = card.to_summary()
    assert "action" in summary and "checks" in summary
    lines = card.render_lines()
    assert any(line.startswith("Action:") for line in lines)
