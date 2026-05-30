"""Cross-sectional ranking + allocation (Session 11).

Turns per-name composite scores (see :mod:`scoring`) into an opportunity-cost
view across the whole watchlist: a percentile relative-strength rank, a best→worst
ordering, and a suggested allocation across the top names. All suggestions —
never executed. Pure/deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.core.config import settings


def rs_rank(values: dict[str, float]) -> dict[str, float]:
    """Percentile rank (0-100) of each name's value within the cohort.

    100 = strongest in the group, 0 = weakest. Uses the midrank convention so
    ties share a percentile. An empty/singleton cohort returns 100 for each name.
    """
    n = len(values)
    if n == 0:
        return {}
    if n == 1:
        return {k: 100.0 for k in values}
    out: dict[str, float] = {}
    for k, v in values.items():
        below = sum(1 for x in values.values() if x < v)
        equal = sum(1 for x in values.values() if x == v)
        out[k] = (below + 0.5 * (equal - 1)) / (n - 1) * 100.0
    return out


@dataclass(frozen=True)
class ScoredName:
    ticker: str
    score: float  # 0-100 composite
    rs_value: float | None = None  # relative-strength delta used for the percentile


@dataclass(frozen=True)
class RankedOpportunity:
    ticker: str
    score: float
    rank: int  # 1 = best
    n: int  # cohort size
    rs_percentile: float | None = None

    def label(self) -> str:
        return f"{self.score:.0f}/100 · #{self.rank} of {self.n}"

    def to_summary(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "score": round(self.score, 1),
            "rank": self.rank,
            "n": self.n,
            "rs_percentile": None if self.rs_percentile is None else round(self.rs_percentile, 1),
        }


def rank_opportunities(names: list[ScoredName]) -> list[RankedOpportunity]:
    """Order names best→worst by composite score; attach rank + RS percentile."""
    if not names:
        return []
    rs_values = {n.ticker: n.rs_value for n in names if n.rs_value is not None}
    percentiles = rs_rank(rs_values) if rs_values else {}
    ordered = sorted(names, key=lambda x: x.score, reverse=True)
    n = len(ordered)
    return [
        RankedOpportunity(
            ticker=s.ticker,
            score=s.score,
            rank=i + 1,
            n=n,
            rs_percentile=percentiles.get(s.ticker),
        )
        for i, s in enumerate(ordered)
    ]


def suggest_allocation(
    ranked: list[RankedOpportunity], top_n: int | None = None
) -> dict[str, float]:
    """Allocate ~100% across the top ``top_n`` names, proportional to score.

    Returns percentages that sum to ~100 (empty when there are no positive scores).
    """
    top_n = top_n or settings.top_opportunities_n
    top = [r for r in ranked[:top_n] if r.score > 0]
    total = sum(r.score for r in top)
    if total <= 0:
        return {}
    return {r.ticker: r.score / total * 100.0 for r in top}
