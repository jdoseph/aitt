"""Watchlist loading tests, incl. the Session 12 capex_exposure field."""

from __future__ import annotations

import pytest

from src.core.watchlist import WatchlistEntry, load_watchlist


def test_load_watchlist_has_capex_exposure() -> None:
    wl = load_watchlist()
    by_ticker = {e.ticker: e for e in wl.entries}
    assert by_ticker["NVDA"].capex_exposure == 100
    # Every entry carries a valid 0-100 exposure.
    assert all(0 <= e.capex_exposure <= 100 for e in wl.entries)
    # Hyperscaler demand-side names rate higher than the space adjacencies.
    assert by_ticker["MSFT"].capex_exposure > by_ticker["LUNR"].capex_exposure


def test_capex_exposure_defaults_when_omitted() -> None:
    e = WatchlistEntry(ticker="ZZZ", name="Test", layer="layer1")
    assert e.capex_exposure == 50  # capex_exposure_default


def test_capex_exposure_rejects_out_of_range() -> None:
    with pytest.raises(ValueError):
        WatchlistEntry(ticker="ZZZ", name="Test", layer="layer1", capex_exposure=150)
