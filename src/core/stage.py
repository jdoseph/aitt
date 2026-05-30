"""Weinstein Stage Analysis (Session 12).

Classifies a name into one of the four stages of the cycle from weekly price vs
the 30-week MA and the MA's slope. The same daily pullback means very different
things by stage: an ``AT_21_EMA`` touch in Stage 2 (advancing) is a buyable dip;
the same touch in Stage 4 (declining) is a falling knife.

    Stage 1 — Basing      : price churns around a flattening MA after a decline.
    Stage 2 — Advancing   : price above a rising MA (the only stage to buy).
    Stage 3 — Topping      : price stalls around a flattening MA after an advance.
    Stage 4 — Declining   : price below a falling MA.

Pure functions over a date-indexed daily OHLCV frame.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from src.core import multitimeframe as mtf
from src.core.config import settings

STAGE_NAMES = {1: "basing", 2: "advancing", 3: "topping", 4: "declining"}


@dataclass(frozen=True)
class StageResult:
    stage: int  # 1-4, or 0 when history is too thin to classify
    name: str
    above_ma: bool | None
    slope_pct: float | None

    @property
    def is_advancing(self) -> bool:
        return self.stage == 2

    @property
    def is_declining(self) -> bool:
        return self.stage == 4

    def to_summary(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "name": self.name,
            "above_ma": self.above_ma,
            "slope_pct": None if self.slope_pct is None else round(self.slope_pct, 2),
        }


def classify_stage(df: pd.DataFrame, weeks: int | None = None) -> StageResult:
    """Classify the Weinstein stage from the weekly 30-week MA and its slope."""
    wt = mtf.weekly_trend(df, weeks)
    if wt.above_ma is None or wt.slope_pct is None:
        return StageResult(0, "unknown", None, None)

    flat = settings.weekly_slope_flat_pct
    rising = wt.slope_pct > flat
    falling = wt.slope_pct < -flat

    if wt.above_ma and rising:
        stage = 2  # advancing
    elif (not wt.above_ma) and falling:
        stage = 4  # declining
    elif wt.above_ma:
        stage = 3  # topping (above a flat/rolling MA)
    else:
        stage = 1  # basing (below a flat MA, no longer falling)
    return StageResult(stage, STAGE_NAMES[stage], wt.above_ma, wt.slope_pct)
