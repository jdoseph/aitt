"""Catalysts (Session 8): recent headlines + an earnings beat/miss heuristic.

Headlines are **context only** ("why is it moving?") — they never grade a setup,
because judging a headline good/bad needs NLP we deliberately avoid. The only
signed, structured catalyst we grade on is the earnings beat/miss (reported vs
estimate EPS). Network access is isolated in the ``_raw_*`` helpers so the pure
transforms are unit-testable.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from loguru import logger

from src.core.config import settings


# --------------------------------------------------------------------------- #
# Raw accessors (network) — patched out in tests
# --------------------------------------------------------------------------- #
def _raw_news(ticker: str) -> list[dict[str, Any]]:
    import yfinance as yf

    return list(yf.Ticker(ticker).news or [])


def _raw_earnings(ticker: str) -> Any:
    import yfinance as yf

    return yf.Ticker(ticker).get_earnings_dates(limit=12)


# --------------------------------------------------------------------------- #
# Headlines (context only)
# --------------------------------------------------------------------------- #
def _normalize_item(item: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize one yfinance news item across the old and new (``content``) shapes."""
    content = item.get("content")
    if isinstance(content, dict):  # newer yfinance schema
        title = content.get("title", "")
        provider = (content.get("provider") or {}).get("displayName", "")
        published = content.get("pubDate") or content.get("displayTime", "")
        url = (content.get("canonicalUrl") or content.get("clickThroughUrl") or {}).get("url", "")
        ts = _parse_iso(published)
    else:  # legacy flat schema
        title = item.get("title", "")
        provider = item.get("publisher", "")
        epoch = item.get("providerPublishTime")
        ts = datetime.fromtimestamp(epoch, tz=timezone.utc) if epoch else None
        url = item.get("link", "")
    if not title:
        return None
    return {"title": title, "publisher": provider, "published": ts, "link": url}


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def recent_headlines(
    ticker: str,
    days: int | None = None,
    max_items: int | None = None,
    _raw: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Recent headlines within ``days``, newest first, capped at ``max_items``."""
    days = days if days is not None else settings.news_days
    max_items = max_items if max_items is not None else settings.news_max_items
    raw = _raw if _raw is not None else _safe(lambda: _raw_news(ticker), default=[])

    cutoff = datetime.now(timezone.utc).timestamp() - days * 86400
    items = []
    for it in raw:
        norm = _normalize_item(it)
        if norm is None:
            continue
        ts = norm["published"]
        if ts is not None and ts.timestamp() < cutoff:
            continue
        items.append(norm)
    items.sort(key=lambda d: (d["published"] or datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
    return items[:max_items]


# --------------------------------------------------------------------------- #
# Earnings beat/miss (the only graded catalyst)
# --------------------------------------------------------------------------- #
def earnings_beat(ticker: str, _raw: Any = None) -> str | None:
    """Most recent reported-quarter result: 'beat' | 'miss' | 'inline' | None."""
    df = _raw if _raw is not None else _safe(lambda: _raw_earnings(ticker), default=None)
    if df is None or getattr(df, "empty", True):
        return None
    cols = {c.lower(): c for c in df.columns}
    rep_col = cols.get("reported eps")
    est_col = cols.get("eps estimate")
    if rep_col is None or est_col is None:
        return None
    reported = df[df[rep_col].notna()]
    if reported.empty:
        return None
    row = reported.iloc[0]  # get_earnings_dates is newest-first
    rep, est = row[rep_col], row[est_col]
    if est is None or (isinstance(est, float) and est != est):  # NaN guard
        return None
    if rep > est:
        return "beat"
    if rep < est:
        return "miss"
    return "inline"


def _safe(fn: Any, default: Any) -> Any:
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - yfinance news/earnings are best-effort
        logger.debug("news/earnings fetch failed: {}", exc)
        return default
