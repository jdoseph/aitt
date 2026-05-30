"""Catalyst (headlines + earnings beat/miss) tests (Session 8)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from src.core import news


def _epoch(dt: datetime) -> int:
    return int(dt.timestamp())


def test_recent_headlines_legacy_schema_filters_old() -> None:
    now = datetime.now(timezone.utc)
    raw = [
        {"title": "Fresh news", "publisher": "Reuters", "providerPublishTime": _epoch(now), "link": "u1"},
        {"title": "Stale news", "publisher": "WSJ",
         "providerPublishTime": _epoch(now - timedelta(days=30)), "link": "u2"},
    ]
    out = news.recent_headlines("X", days=7, max_items=5, _raw=raw)
    titles = [h["title"] for h in out]
    assert titles == ["Fresh news"]


def test_recent_headlines_new_content_schema() -> None:
    now = datetime.now(timezone.utc)
    raw = [
        {
            "content": {
                "title": "New-schema headline",
                "provider": {"displayName": "Bloomberg"},
                "pubDate": now.isoformat(),
                "canonicalUrl": {"url": "http://x"},
            }
        }
    ]
    out = news.recent_headlines("X", days=7, _raw=raw)
    assert out and out[0]["title"] == "New-schema headline"
    assert out[0]["publisher"] == "Bloomberg"


def test_recent_headlines_caps_max_items() -> None:
    now = datetime.now(timezone.utc)
    raw = [
        {"title": f"h{i}", "publisher": "P", "providerPublishTime": _epoch(now), "link": ""}
        for i in range(10)
    ]
    assert len(news.recent_headlines("X", days=7, max_items=3, _raw=raw)) == 3


def _earnings_df(rows: list[tuple]) -> pd.DataFrame:
    # newest-first, like yfinance get_earnings_dates
    idx = pd.to_datetime([r[0] for r in rows])
    return pd.DataFrame(
        {"EPS Estimate": [r[1] for r in rows], "Reported EPS": [r[2] for r in rows]}, index=idx
    )


def test_earnings_beat() -> None:
    df = _earnings_df([("2026-08-01", 1.0, None), ("2026-05-01", 1.0, 1.3)])  # latest reported beat
    assert news.earnings_beat("X", _raw=df) == "beat"


def test_earnings_miss() -> None:
    df = _earnings_df([("2026-05-01", 1.0, 0.7)])
    assert news.earnings_beat("X", _raw=df) == "miss"


def test_earnings_inline() -> None:
    df = _earnings_df([("2026-05-01", 1.0, 1.0)])
    assert news.earnings_beat("X", _raw=df) == "inline"


def test_earnings_none_when_no_reported() -> None:
    df = _earnings_df([("2026-08-01", 1.0, None)])
    assert news.earnings_beat("X", _raw=df) is None
