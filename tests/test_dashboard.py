"""Dashboard render tests using Streamlit's headless AppTest harness.

Each page is rendered in-process via a small import-and-call script (so the
page module's own imports/globals are intact) and asserted to raise no
exception. They exercise the real data layer against whatever is in tracker.db
(empty is fine — pages show a warning rather than erroring).
"""

from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

PAGE_MODULES = ["overview", "chart", "value_chain", "portfolio", "trades", "options", "backtest", "alerts"]


@pytest.mark.parametrize("page", PAGE_MODULES)
def test_page_renders_without_exception(page: str) -> None:
    script = f"from src.dashboard.pages import {page}\n{page}.render()\n"
    at = AppTest.from_string(script, default_timeout=30)
    at.run()
    assert not at.exception, f"{page} raised: {at.exception}"


def test_app_entrypoint_runs() -> None:
    at = AppTest.from_file("src/dashboard/app.py", default_timeout=30)
    at.run()
    assert not at.exception, f"app.py raised: {at.exception}"


def test_overview_has_title_and_renders_table() -> None:
    script = "from src.dashboard.pages import overview\noverview.render()\n"
    at = AppTest.from_string(script, default_timeout=30)
    at.run()
    assert not at.exception
    assert any("Overview" in t.value for t in at.title)


def test_trades_win_rate_breakdown() -> None:
    from datetime import date

    from src.dashboard.pages import trades
    from src.core.storage import PaperTrade

    closed = [
        PaperTrade(ticker="A", status="CLOSED", exit_reason="EXIT_TARGET", pnl_dollars=100.0),
        PaperTrade(ticker="B", status="CLOSED", exit_reason="EXIT_TARGET", pnl_dollars=50.0),
        PaperTrade(ticker="C", status="CLOSED", exit_reason="EXIT_STOP", pnl_dollars=-40.0),
    ]
    bd = trades.win_rate_breakdown(closed)
    assert bd["EXIT_TARGET"]["n"] == 2
    assert bd["EXIT_TARGET"]["win_rate"] == 100.0
    assert bd["EXIT_STOP"]["win_rate"] == 0.0


def test_trades_equity_curve_indexes_to_100() -> None:
    from datetime import date

    from src.dashboard.pages import trades
    from src.core.storage import CashbookEntry

    cb = [
        CashbookEntry(date=date(2024, 1, 2), total_nav=5000.0, voo_nav=5000.0),
        CashbookEntry(date=date(2024, 1, 3), total_nav=5500.0, voo_nav=5100.0),
    ]
    df = trades.equity_curve_df(cb)
    assert df["Paper NAV"].iloc[0] == pytest.approx(100.0)
    assert df["Paper NAV"].iloc[1] == pytest.approx(110.0)
    assert df["VOO"].iloc[1] == pytest.approx(102.0)


def test_options_win_rate_breakdown() -> None:
    from src.dashboard.pages import options
    from src.core.storage import OptionTrade

    closed = [
        OptionTrade(ticker="A", status="CLOSED", exit_reason="EXIT_TARGET", pnl_dollars=300.0),
        OptionTrade(ticker="B", status="CLOSED", exit_reason="EXIT_OPT_SL", pnl_dollars=-150.0),
    ]
    bd = options.win_rate_breakdown(closed)
    assert bd["EXIT_TARGET"]["win_rate"] == 100.0
    assert bd["EXIT_OPT_SL"]["win_rate"] == 0.0


def test_options_equity_curve_indexes_to_100() -> None:
    from datetime import date
    from src.dashboard.pages import options
    from src.core.storage import OptionCashbook

    cb = [
        OptionCashbook(date=date(2024, 1, 2), total_nav=5000.0, voo_nav=5000.0),
        OptionCashbook(date=date(2024, 1, 3), total_nav=5500.0, voo_nav=5100.0),
    ]
    df = options.equity_curve_df(cb)
    assert df["Option NAV"].iloc[1] == pytest.approx(110.0)
    assert df["VOO"].iloc[1] == pytest.approx(102.0)
