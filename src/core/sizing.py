"""Conviction sizing + concentration caps + RS rotation + turnover bands (Session 13).

Given the cross-sectional ranking (Session 11), an exposure budget (the
:mod:`exposure` dial), and the current paper holdings, produce target weights
and a list of rebalance *suggestions*. The three levers that let a concentrated
thematic book beat the index:

  1. **Conviction sizing** — weight the top ``max_positions`` names ∝ composite
     score (not equal-weight), normalized to the exposure budget.
  2. **Concentration cap** — no single name exceeds ``max_position_pct`` (excess
     water-fills to the others); a ``min_position_pct`` floor drops dust.
  3. **RS rotation** — a held name is EXITed when it falls past ``exit_rank``,
     loses its 50 EMA, or trips a disqualifier; names in the hold band
     (``max_positions+1 .. exit_rank``) are kept but not added to.

A ``rebalance_threshold_pct`` no-trade band suppresses tiny ADD/TRIM drifts so
the book isn't churned to death. Everything is a suggestion — never executed.
Pure/deterministic.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from src.core.config import settings

# Scorecard grades, worst → best (mirrors scorecard._ACTIONS) for min-grade gating.
_GRADE_ORDER = ["AVOID", "MARGINAL", "DECENT", "HIGH-QUALITY"]

ENTER, ADD, TRIM, EXIT, HOLD = "ENTER", "ADD", "TRIM", "EXIT", "HOLD"


@dataclass(frozen=True)
class Candidate:
    """A ranked name the sizer can act on (derived from the cycle's ranking)."""

    ticker: str
    score: float  # 0-100 composite
    rank: int  # 1 = best (cross-sectional)
    grade: str  # scorecard action: HIGH-QUALITY | DECENT | MARGINAL | AVOID
    disqualified: bool = False
    above_50_ema: bool = True


@dataclass(frozen=True)
class RebalanceAction:
    """A single paper-portfolio suggestion (never auto-executed)."""

    ticker: str
    action: str  # ENTER | ADD | TRIM | EXIT
    current_weight: float
    target_weight: float
    reason: str = ""

    def summary(self) -> str:
        cw, tw = self.current_weight * 100, self.target_weight * 100
        if self.action == EXIT:
            return f"EXIT {self.ticker} ({cw:.0f}%→0%)" + (f" — {self.reason}" if self.reason else "")
        if self.action == ENTER:
            return f"ENTER {self.ticker} ({tw:.0f}%)"
        return f"{self.action} {self.ticker} ({cw:.0f}%→{tw:.0f}%)"


@dataclass(frozen=True)
class SizingPlan:
    target_weights: dict[str, float] = field(default_factory=dict)  # ticker -> 0-1 fraction
    actions: list[RebalanceAction] = field(default_factory=list)  # meaningful suggestions only
    exposure: float = 0.0


def _grade_ge(grade: str, minimum: str) -> bool:
    if grade not in _GRADE_ORDER or minimum not in _GRADE_ORDER:
        return False
    return _GRADE_ORDER.index(grade) >= _GRADE_ORDER.index(minimum)


def _proportional_with_caps(scores: dict[str, float], budget: float, cap: float) -> dict[str, float]:
    """Allocate ``budget`` ∝ score, clipping any name to ``cap`` (water-filling).

    Names hitting the cap are fixed at ``cap`` and the remaining budget is shared
    proportionally among the uncapped names, repeating until stable.
    """
    weights = {t: 0.0 for t in scores}
    capped: set[str] = set()
    while True:
        remaining_budget = budget - sum(cap for _ in capped)
        free = {t: s for t, s in scores.items() if t not in capped}
        free_total = sum(free.values())
        if remaining_budget <= 0 or free_total <= 0:
            for t in free:
                weights[t] = 0.0
            break
        newly_capped = False
        for t, s in free.items():
            w = s / free_total * remaining_budget
            if w > cap + 1e-12:
                capped.add(t)
                weights[t] = cap
                newly_capped = True
            else:
                weights[t] = w
        if not newly_capped:
            break
    return weights


def _conviction_weights(
    selected: list[Candidate], exposure: float, cap: float, floor: float
) -> dict[str, float]:
    """Top-N conviction weights: ∝ score, capped, dust dropped, summing to exposure."""
    pool = list(selected)
    while pool:
        scores = {c.ticker: c.score for c in pool}
        weights = _proportional_with_caps(scores, exposure, cap)
        dust = [t for t, w in weights.items() if w < floor]
        if not dust:
            return {t: w for t, w in weights.items() if w > 0}
        dust_set = set(dust)
        pool = [c for c in pool if c.ticker not in dust_set]
    return {}


def target_weights(
    candidates: Sequence[Candidate],
    exposure: float,
    held: Mapping[str, float],
    *,
    max_positions: int | None = None,
    max_position_pct: float | None = None,
    min_position_pct: float | None = None,
    exit_rank: int | None = None,
    min_grade: str | None = None,
    rebalance_threshold_pct: float | None = None,
) -> SizingPlan:
    """Build target weights + rebalance suggestions from ranked candidates.

    ``held`` maps currently-held tickers to their current weight (0-1).
    """
    max_positions = max_positions or settings.max_positions
    cap = max_position_pct if max_position_pct is not None else settings.max_position_pct
    floor = min_position_pct if min_position_pct is not None else settings.min_position_pct
    exit_rank = exit_rank or settings.exit_rank
    min_grade = min_grade or settings.min_grade
    band = (
        rebalance_threshold_pct
        if rebalance_threshold_pct is not None
        else settings.rebalance_threshold_pct
    )

    by_ticker = {c.ticker: c for c in candidates}

    # --- conviction book: top-N eligible names, weighted by score ---
    # A name below its 50 EMA, disqualified, or under min_grade can't be in the
    # book — so a held name that loses its 50 EMA is forced out via rotation below.
    eligible = sorted(
        (
            c
            for c in candidates
            if not c.disqualified and c.above_50_ema and _grade_ge(c.grade, min_grade)
        ),
        key=lambda c: c.score,
        reverse=True,
    )[:max_positions]
    targets = _conviction_weights(eligible, exposure, cap, floor)

    # --- rotation: decide each held name's fate ---
    for ticker, current in held.items():
        if ticker in targets:
            continue  # already a top-N target; handled by the conviction book
        cand = by_ticker.get(ticker)
        if cand is None or cand.rank > exit_rank or not cand.above_50_ema or cand.disqualified:
            targets[ticker] = 0.0  # EXIT (reason attached when the action is built)
        else:
            targets[ticker] = current  # hold band — kept, not added to

    # --- diff targets vs current holdings into suggestions (no-trade band) ---
    actions: list[RebalanceAction] = []
    for ticker in sorted(set(targets) | set(held), key=lambda t: -targets.get(t, 0.0)):
        current = held.get(ticker, 0.0)
        target = targets.get(ticker, 0.0)
        delta = target - current
        if target <= 0.0 and current > 0.0:
            actions.append(
                RebalanceAction(ticker, EXIT, current, 0.0, reason=_exit_reason(by_ticker.get(ticker), exit_rank))
            )
        elif current <= 0.0 and target > 0.0:
            actions.append(RebalanceAction(ticker, ENTER, 0.0, target))
        elif abs(delta) > band:
            actions.append(RebalanceAction(ticker, ADD if delta > 0 else TRIM, current, target))
        # else: within the no-trade band → HOLD, no suggestion emitted

    # Drop the zero-weight EXIT placeholders from the held target map.
    clean_targets = {t: w for t, w in targets.items() if w > 0.0}
    return SizingPlan(target_weights=clean_targets, actions=actions, exposure=exposure)


def _exit_reason(cand: Candidate | None, exit_rank: int) -> str:
    if cand is None:
        return "off the board"
    if cand.disqualified:
        return "disqualified"
    if not cand.above_50_ema:
        return "lost 50 EMA"
    if cand.rank > exit_rank:
        return f"rank #{cand.rank} > {exit_rank}"
    return ""
