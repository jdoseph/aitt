"""Weinstein stage classification tests (Session 12)."""

from __future__ import annotations

from src.core import stage
from tests.factories import make_ohlcv


def _daily(closes: list[float]) -> "object":
    return make_ohlcv(closes)


def test_stage_2_on_steady_advance() -> None:
    # Long advance: price above a rising 30-week MA.
    df = _daily([100.0 + i for i in range(250)])
    r = stage.classify_stage(df)
    assert r.stage == 2
    assert r.name == "advancing"
    assert r.is_advancing and not r.is_declining


def test_stage_4_on_steady_decline() -> None:
    df = _daily([400.0 - i for i in range(250)])
    r = stage.classify_stage(df)
    assert r.stage == 4
    assert r.name == "declining"
    assert r.is_declining and not r.is_advancing


def test_stage_unknown_when_thin() -> None:
    df = _daily([100.0 + i for i in range(40)])  # < 30 weeks
    r = stage.classify_stage(df)
    assert r.stage == 0
    assert r.above_ma is None


def test_stage_summary_serializable() -> None:
    import json

    r = stage.classify_stage(_daily([100.0 + i for i in range(250)]))
    json.dumps(r.to_summary())
