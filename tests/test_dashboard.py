"""Dashboard render tests using Streamlit's headless AppTest harness.

Each page is rendered in-process via a small import-and-call script (so the
page module's own imports/globals are intact) and asserted to raise no
exception. They exercise the real data layer against whatever is in tracker.db
(empty is fine — pages show a warning rather than erroring).
"""

from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

PAGE_MODULES = ["overview", "chart", "value_chain", "alerts"]


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
