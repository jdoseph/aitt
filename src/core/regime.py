"""Canonical market-regime gate (Session 10).

Reads SPY / QQQ / SMH against their **50 EMA** and labels the tape
``RISK_ON`` / ``NEUTRAL`` / ``RISK_OFF``. This is the gating regime that the
orchestrator uses to suppress or de-prioritize alerts — distinct from Session
9's *informational* 21-EMA line in :mod:`src.core.benchmarks`.

Rule: RISK_OFF when ``>= regime_risk_off_fails`` of the available indices are
below their 50 EMA; RISK_ON when all available indices are above; otherwise
NEUTRAL. Unknown (no benchmark data) degrades to NEUTRAL.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.core.benchmarks import above_own_ema
from src.core.config import settings

RISK_ON = "RISK_ON"
NEUTRAL = "NEUTRAL"
RISK_OFF = "RISK_OFF"

_BADGE = {RISK_ON: "🟢 RISK_ON", NEUTRAL: "🟡 NEUTRAL", RISK_OFF: "🔴 RISK_OFF"}


@dataclass(frozen=True)
class Regime:
    label: str  # RISK_ON | NEUTRAL | RISK_OFF
    flags: dict[str, bool]  # symbol -> above its 50 EMA
    span: int

    @property
    def is_risk_off(self) -> bool:
        return self.label == RISK_OFF

    @property
    def is_risk_on(self) -> bool:
        return self.label == RISK_ON

    @property
    def n_below(self) -> int:
        return sum(1 for ok in self.flags.values() if not ok)

    def badge(self) -> str:
        return _BADGE.get(self.label, self.label)

    def summary(self) -> str:
        if not self.flags:
            return f"{self.label} (no benchmark data)"
        below = [s for s, ok in self.flags.items() if not ok]
        if not below:
            return f"{self.label} (all above {self.span} EMA)"
        return f"{self.label} ({', '.join(below)} below {self.span} EMA)"


def market_regime(
    benchmarks: dict[str, pd.DataFrame],
    span: int | None = None,
    risk_off_fails: int | None = None,
) -> Regime:
    """Label the tape from the benchmark frames already fetched this cycle."""
    span = span or settings.regime_gate_ema_span
    risk_off_fails = settings.regime_risk_off_fails if risk_off_fails is None else risk_off_fails

    flags: dict[str, bool] = {}
    for sym, df in benchmarks.items():
        ok = above_own_ema(df, span)
        if ok is not None:
            flags[sym] = ok

    if not flags:
        label = NEUTRAL
    else:
        n_below = sum(1 for ok in flags.values() if not ok)
        if n_below >= risk_off_fails:
            label = RISK_OFF
        elif n_below == 0:
            label = RISK_ON
        else:
            label = NEUTRAL
    return Regime(label=label, flags=flags, span=span)
