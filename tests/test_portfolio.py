"""Session 13: paper-portfolio NAV math + apply_targets bookkeeping.

A simulated book: cash + share positions, valued at the latest closes. Rebalancing
to target weights is costless here (turnover costs arrive in the Session 14
backtest). Everything is hypothetical — no live execution.
"""

from __future__ import annotations

import pytest

from src.core.portfolio import PaperPortfolio, Position


def test_empty_portfolio_nav_is_cash() -> None:
    pf = PaperPortfolio.empty(5000.0)
    assert pf.cash == 5000.0
    assert pf.nav({}) == 5000.0
    assert pf.current_weights({}) == {}


def test_nav_includes_position_market_value() -> None:
    pf = PaperPortfolio(cash=1000.0, positions={"A": Position("A", shares=10.0, entry=100.0)})
    # 1000 cash + 10 shares * $150 = 2500
    assert pf.nav({"A": 150.0}) == pytest.approx(2500.0)


def test_apply_targets_buys_to_weights_and_conserves_nav() -> None:
    pf = PaperPortfolio.empty(5000.0)
    pf.apply_targets({"A": 0.5, "B": 0.5}, {"A": 100.0, "B": 50.0})
    assert pf.positions["A"].shares == pytest.approx(25.0)  # 2500 / 100
    assert pf.positions["B"].shares == pytest.approx(50.0)  # 2500 / 50
    assert pf.cash == pytest.approx(0.0)
    # A costless rebalance conserves NAV.
    assert pf.nav({"A": 100.0, "B": 50.0}) == pytest.approx(5000.0)


def test_current_weights_after_rebalance() -> None:
    pf = PaperPortfolio.empty(5000.0)
    prices = {"A": 100.0, "B": 50.0}
    pf.apply_targets({"A": 0.5, "B": 0.5}, prices)
    w = pf.current_weights(prices)
    assert w["A"] == pytest.approx(0.5)
    assert w["B"] == pytest.approx(0.5)


def test_partial_exposure_leaves_cash() -> None:
    pf = PaperPortfolio.empty(5000.0)
    pf.apply_targets({"A": 0.6}, {"A": 100.0})  # 60% invested
    assert pf.cash == pytest.approx(2000.0)  # 40% in cash
    assert pf.positions["A"].shares == pytest.approx(30.0)  # 3000 / 100


def test_apply_targets_exits_names_not_in_target() -> None:
    pf = PaperPortfolio.empty(5000.0)
    pf.apply_targets({"A": 0.5, "B": 0.5}, {"A": 100.0, "B": 50.0})
    # Rebalance to A only — B is fully sold back to cash.
    pf.apply_targets({"A": 1.0}, {"A": 100.0, "B": 50.0})
    assert "B" not in pf.positions
    assert pf.positions["A"].shares == pytest.approx(50.0)  # 5000 / 100
    assert pf.cash == pytest.approx(0.0)


def test_weights_drift_as_prices_move() -> None:
    pf = PaperPortfolio.empty(2000.0)
    pf.apply_targets({"A": 0.5, "B": 0.5}, {"A": 100.0, "B": 100.0})
    # A doubles, B flat: A is now 2/3 of the book.
    w = pf.current_weights({"A": 200.0, "B": 100.0})
    assert w["A"] == pytest.approx(2 / 3, abs=1e-6)
    assert w["B"] == pytest.approx(1 / 3, abs=1e-6)


def test_round_trip_serialization() -> None:
    pf = PaperPortfolio.empty(5000.0)
    pf.apply_targets({"A": 0.5}, {"A": 100.0})
    restored = PaperPortfolio.from_dict(pf.to_dict())
    assert restored.cash == pytest.approx(pf.cash)
    assert restored.positions["A"].shares == pytest.approx(pf.positions["A"].shares)
