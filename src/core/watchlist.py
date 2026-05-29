"""Watchlist loading, validation, and hot-reload.

The watchlist lives in a single YAML file (see ``watchlist.yaml``) so it is
trivially editable. The agent calls :func:`load_watchlist` at the start of each
evaluation cycle; :class:`WatchlistCache` reloads only when the file's mtime
changes, giving cheap hot-reload.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, field_validator

from src.core.config import settings


class WatchlistEntry(BaseModel):
    """A single tracked instrument."""

    ticker: str
    name: str
    layer: str
    notes: str = ""

    @field_validator("ticker")
    @classmethod
    def _normalize_ticker(cls, v: str) -> str:
        v = v.strip().upper()
        if not v:
            raise ValueError("ticker must be non-empty")
        return v


class Watchlist(BaseModel):
    """Validated watchlist: ordered layer titles + entries."""

    layers: dict[str, str]
    entries: list[WatchlistEntry]

    @field_validator("entries")
    @classmethod
    def _entries_non_empty(cls, v: list[WatchlistEntry]) -> list[WatchlistEntry]:
        if not v:
            raise ValueError("watchlist has no tickers")
        return v

    def model_post_init(self, __context: object) -> None:
        # Every entry's layer must be a declared layer key.
        unknown = {e.layer for e in self.entries} - set(self.layers)
        if unknown:
            raise ValueError(f"entries reference undeclared layer(s): {sorted(unknown)}")
        # No duplicate tickers.
        seen: set[str] = set()
        dupes = {t for e in self.entries if (t := e.ticker) in seen or seen.add(t)}  # type: ignore[func-returns-value]
        if dupes:
            raise ValueError(f"duplicate tickers in watchlist: {sorted(dupes)}")

    @property
    def tickers(self) -> list[str]:
        """All ticker symbols, in file order."""
        return [e.ticker for e in self.entries]

    def by_layer(self) -> dict[str, list[WatchlistEntry]]:
        """Entries grouped by layer, preserving the declared layer order."""
        grouped: dict[str, list[WatchlistEntry]] = {k: [] for k in self.layers}
        for e in self.entries:
            grouped[e.layer].append(e)
        return grouped

    def layer_title(self, layer_key: str) -> str:
        return self.layers.get(layer_key, layer_key)


def _parse_watchlist(raw: dict) -> Watchlist:
    layers = raw.get("layers") or {}
    tickers = raw.get("tickers") or []
    return Watchlist(
        layers=layers,
        entries=[WatchlistEntry.model_validate(t) for t in tickers],
    )


def load_watchlist(path: Path | str | None = None) -> Watchlist:
    """Load and validate the watchlist from YAML.

    Args:
        path: Override the configured watchlist path (useful for tests).

    Raises:
        FileNotFoundError: if the file is missing.
        ValueError / pydantic.ValidationError: on schema problems.
    """
    p = Path(path) if path is not None else settings.watchlist_path
    if not p.exists():
        raise FileNotFoundError(f"watchlist not found: {p}")
    with p.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return _parse_watchlist(raw)


class WatchlistCache:
    """Caches the parsed watchlist and reloads only when the file mtime changes."""

    def __init__(self, path: Path | str | None = None) -> None:
        self._path = Path(path) if path is not None else settings.watchlist_path
        self._mtime: float | None = None
        self._cached: Watchlist | None = None

    def get(self) -> Watchlist:
        """Return the watchlist, reloading from disk if it changed since last read."""
        mtime = self._path.stat().st_mtime
        if self._cached is None or mtime != self._mtime:
            self._cached = load_watchlist(self._path)
            self._mtime = mtime
        return self._cached
