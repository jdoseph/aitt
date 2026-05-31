"""Session 13: regime → exposure dial with hysteresis.

The dial is a pure fold over the regime history: the first reading is the
baseline, and after that a *new* regime must persist `regime_confirm_days`
consecutive days before it moves the dial. A one-day flip must not move it —
this is the mandatory whipsaw guard.
"""

from __future__ import annotations

from src.core import exposure
from src.core.config import settings
from src.core.regime import NEUTRAL, RISK_OFF, RISK_ON


def test_empty_history_is_neutral_exposure() -> None:
    result = exposure.target_exposure([])
    assert result.exposure == settings.target_exposure_neutral
    assert result.regime == NEUTRAL


def test_all_risk_on_gives_full_exposure() -> None:
    result = exposure.target_exposure([RISK_ON, RISK_ON, RISK_ON])
    assert result.exposure == settings.target_exposure_on
    assert result.regime == RISK_ON


def test_one_day_flip_does_not_move_the_dial() -> None:
    # Three days RISK_ON then a single RISK_OFF day — the dial stays RISK_ON.
    result = exposure.target_exposure(
        [RISK_ON, RISK_ON, RISK_ON, RISK_OFF], confirm_days=3
    )
    assert result.regime == RISK_ON
    assert result.exposure == settings.target_exposure_on
    # ...but the system flags the building (un-confirmed) regime.
    assert result.pending == RISK_OFF
    assert result.days_pending == 1


def test_three_day_persistent_flip_moves_the_dial() -> None:
    result = exposure.target_exposure(
        [RISK_ON, RISK_ON, RISK_OFF, RISK_OFF, RISK_OFF], confirm_days=3
    )
    assert result.regime == RISK_OFF
    assert result.exposure == settings.target_exposure_off
    assert result.pending is None  # the change is confirmed, nothing pending


def test_two_day_flip_is_still_not_enough() -> None:
    result = exposure.target_exposure(
        [RISK_ON, RISK_ON, RISK_OFF, RISK_OFF], confirm_days=3
    )
    assert result.regime == RISK_ON
    assert result.days_pending == 2


def test_first_reading_is_the_baseline_no_confirmation() -> None:
    # A brand-new history that opens RISK_OFF commits immediately (no prior dial).
    result = exposure.target_exposure([RISK_OFF], confirm_days=3)
    assert result.regime == RISK_OFF
    assert result.exposure == settings.target_exposure_off


def test_neutral_maps_to_neutral_exposure() -> None:
    result = exposure.target_exposure([NEUTRAL, NEUTRAL, NEUTRAL])
    assert result.exposure == settings.target_exposure_neutral


def test_exposure_for_maps_each_label() -> None:
    assert exposure.exposure_for(RISK_ON) == settings.target_exposure_on
    assert exposure.exposure_for(NEUTRAL) == settings.target_exposure_neutral
    assert exposure.exposure_for(RISK_OFF) == settings.target_exposure_off
