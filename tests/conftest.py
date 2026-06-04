"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from src.core.storage import Storage


@pytest.fixture
def storage() -> Storage:
    """An isolated in-memory DB for a single test."""
    return Storage.in_memory()
