"""Live option-chain fetch + parse (Session 16)."""

from __future__ import annotations

from datetime import date

import pandas as pd

from src.core.options import chain as ch


class _FakeChain:
    def __init__(self, calls: pd.DataFrame) -> None:
        self.calls = calls
        self.puts = pd.DataFrame()


class _FakeTicker:
    def __init__(self, expiries: tuple[str, ...], calls: pd.DataFrame) -> None:
        self.options = expiries
        self._calls = calls

    def option_chain(self, expiry: str) -> _FakeChain:
        return _FakeChain(self._calls)


def test_fetch_chain_parses_calls() -> None:
    calls = pd.DataFrame(
        {"strike": [95.0, 100.0], "bid": [7.0, 4.0], "ask": [7.4, 4.3],
         "impliedVolatility": [0.33, 0.31], "openInterest": [500, 800]}
    )
    t = _FakeTicker(("2024-04-19", "2024-05-17"), calls)
    out = ch.fetch_chain("NVDA", target_dte=45, as_of=date(2024, 3, 1),
                         ticker_factory=lambda s: t, min_oi=10)
    assert out is not None
    assert out["expiry"] == date(2024, 4, 19)
    assert out["calls"][0]["strike"] == 95.0
    assert out["calls"][0]["iv"] == 0.33


def test_fetch_chain_thin_oi_returns_none() -> None:
    calls = pd.DataFrame(
        {"strike": [95.0], "bid": [7.0], "ask": [7.4],
         "impliedVolatility": [0.33], "openInterest": [1]}  # below min_oi
    )
    t = _FakeTicker(("2024-04-19",), calls)
    out = ch.fetch_chain("NVDA", target_dte=45, as_of=date(2024, 3, 1),
                         ticker_factory=lambda s: t, min_oi=10)
    assert out is None


def test_fetch_chain_no_expiries_returns_none() -> None:
    t = _FakeTicker((), pd.DataFrame())
    out = ch.fetch_chain("RDW", target_dte=45, as_of=date(2024, 3, 1),
                         ticker_factory=lambda s: t)
    assert out is None
