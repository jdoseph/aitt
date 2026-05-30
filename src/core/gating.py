"""Automatic disqualifiers (Session 10).

Hard rules that suppress (or downgrade) an alert regardless of how good the
chart looks — "maximize odds, not signal count." Each rule is individually
toggleable in config and reads from the already-computed scorecard checks
(robust numeric values live on :attr:`Check.num`), so gating stays pure and
deterministic.

:func:`disqualifiers` returns the list of tripped rule descriptions (empty when
the setup is clean). The orchestrator decides what to do with them based on
``disqualifier_mode`` (suppress vs downgrade).
"""

from __future__ import annotations

from typing import Any

from src.core.config import Settings, settings
from src.core.regime import Regime
from src.core.scorecard import FAIL, Scorecard


def _check(card: Scorecard, name: str) -> Any:
    return next((c for c in card.checks if c.name == name), None)


def disqualifiers(
    signal: Any, scorecard: Scorecard, regime: Regime, *, cfg: Settings | None = None
) -> list[str]:
    """Return the hard rules this setup trips (empty list == clean)."""
    cfg = cfg or settings
    out: list[str] = []

    if cfg.dq_below_50ema:
        trend = _check(scorecard, "trend")
        if trend is not None and trend.status == FAIL:
            out.append("price below the 50 EMA")

    if cfg.dq_earnings_days:
        earn = _check(scorecard, "earnings")
        if earn is not None and earn.num is not None and earn.num < cfg.dq_earnings_days:
            out.append(f"earnings in {int(earn.num)}d (< {cfg.dq_earnings_days})")

    if cfg.dq_rs_below_market:
        rs = _check(scorecard, "rel_strength")
        if rs is not None and rs.status == FAIL:
            out.append("relative strength below market")

    if cfg.dq_declining_volume:
        vol = _check(scorecard, "volume")
        if vol is not None and vol.status == FAIL:
            out.append("volume below its 20-day average")

    if cfg.dq_min_rr and cfg.dq_min_rr > 0:
        rr = _check(scorecard, "risk_reward")
        if rr is not None and rr.num is not None and rr.num < cfg.dq_min_rr:
            out.append(f"risk/reward {rr.num:.1f} below {cfg.dq_min_rr}")

    return out
