"""Cross-sectional ranking + allocation tests (Session 11)."""

from __future__ import annotations

import pytest

from src.core import ranking
from src.core.ranking import ScoredName


def test_rs_rank_top_and_bottom() -> None:
    ranks = ranking.rs_rank({"A": 10.0, "B": 5.0, "C": 1.0})
    assert ranks["A"] == pytest.approx(100.0)  # strongest
    assert ranks["C"] == pytest.approx(0.0)  # weakest
    assert 0.0 < ranks["B"] < 100.0


def test_rs_rank_singleton_and_empty() -> None:
    assert ranking.rs_rank({"A": 3.0}) == {"A": 100.0}
    assert ranking.rs_rank({}) == {}


def test_rank_opportunities_orders_best_first() -> None:
    names = [
        ScoredName("LOW", 40.0, rs_value=-2.0),
        ScoredName("HIGH", 90.0, rs_value=5.0),
        ScoredName("MID", 65.0, rs_value=1.0),
    ]
    ranked = ranking.rank_opportunities(names)
    assert [r.ticker for r in ranked] == ["HIGH", "MID", "LOW"]
    assert ranked[0].rank == 1 and ranked[0].n == 3
    assert ranked[0].rs_percentile == pytest.approx(100.0)
    assert "#1 of 3" in ranked[0].label()


def test_suggest_allocation_sums_to_100() -> None:
    names = [ScoredName(f"T{i}", float(s)) for i, s in enumerate([90, 80, 70, 30, 10])]
    ranked = ranking.rank_opportunities(names)
    alloc = ranking.suggest_allocation(ranked, top_n=3)
    assert set(alloc) == {"T0", "T1", "T2"}  # top 3 by score
    assert sum(alloc.values()) == pytest.approx(100.0)
    assert alloc["T0"] > alloc["T2"]  # proportional to score


def test_suggest_allocation_empty_when_no_positive_scores() -> None:
    ranked = ranking.rank_opportunities([ScoredName("Z", 0.0)])
    assert ranking.suggest_allocation(ranked) == {}


def test_rank_opportunities_empty() -> None:
    assert ranking.rank_opportunities([]) == []
