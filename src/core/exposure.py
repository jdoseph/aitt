"""Regime → total-exposure dial with hysteresis (Session 13).

Promotes the Session 10 market regime from an *alert filter* into a
*portfolio-level exposure target* — the cash option the index structurally
lacks. The dial maps each regime to an invested fraction:

    RISK_ON → target_exposure_on  ·  NEUTRAL → target_exposure_neutral  ·
    RISK_OFF → target_exposure_off

**Hysteresis (the mandatory whipsaw guard):** the dial is a deterministic fold
over the regime history. The first reading is taken as the baseline, and after
that a *new* regime must persist for ``regime_confirm_days`` consecutive days
before it moves the dial. A one-day flip does NOT move exposure — a laggy gate
that flip-flops is the single most common way this kind of system bleeds an
account on whipsaws.

Pure/deterministic given the regime history. Paper-only, like everything in
Session 13.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from src.core.config import settings
from src.core.regime import NEUTRAL, RISK_OFF, RISK_ON


def exposure_for(label: str) -> float:
    """Map a regime label to its target invested fraction (0.0-1.0)."""
    return {
        RISK_ON: settings.target_exposure_on,
        NEUTRAL: settings.target_exposure_neutral,
        RISK_OFF: settings.target_exposure_off,
    }.get(label, settings.target_exposure_neutral)


@dataclass(frozen=True)
class ExposureResult:
    """The confirmed exposure target plus any regime building toward a change."""

    exposure: float  # 0.0-1.0 target invested fraction
    regime: str  # the *confirmed* regime driving the dial
    pending: str | None = None  # a regime building toward a change, not yet confirmed
    days_pending: int = 0  # consecutive days the pending regime has persisted


def target_exposure(
    regime_history: Sequence[str], confirm_days: int | None = None
) -> ExposureResult:
    """Resolve the exposure dial from the chronological regime history.

    Args:
        regime_history: regime labels oldest → newest (most recent label last).
        confirm_days: days a new regime must persist before moving the dial
            (defaults to ``settings.regime_confirm_days``).

    The first reading is the baseline (committed immediately). Subsequent
    changes require ``confirm_days`` consecutive identical readings.
    """
    confirm_days = settings.regime_confirm_days if confirm_days is None else confirm_days
    if not regime_history:
        return ExposureResult(exposure=exposure_for(NEUTRAL), regime=NEUTRAL)

    committed = regime_history[0]
    run_label = regime_history[0]
    run_len = 0
    for label in regime_history:
        run_len = run_len + 1 if label == run_label else 1
        run_label = label
        # A new regime that has persisted long enough flips the committed dial.
        if label != committed and run_len >= confirm_days:
            committed = label

    pending = run_label if run_label != committed else None
    days_pending = run_len if pending is not None else 0
    return ExposureResult(
        exposure=exposure_for(committed),
        regime=committed,
        pending=pending,
        days_pending=days_pending,
    )
