"""Colors, labels, and small formatting helpers shared across pages."""

from __future__ import annotations

from typing import Final

# Per-layer accent colors (keyed by the layer keys in watchlist.yaml).
LAYER_COLORS: Final[dict[str, str]] = {
    "layer1": "#76b900",   # NVIDIA green — GPU makers
    "layer2": "#e07b39",   # ASIC co-designers
    "layer3": "#3b82f6",   # semiconductors
    "layer4": "#8b5cf6",   # interconnects
    "layer5": "#ef4444",   # power
    "layer6": "#06b6d4",   # cooling
    "layer7": "#f59e0b",   # OEMs
    "layer8": "#14b8a6",   # REITs
    "layer9": "#ec4899",   # space
    "layer10": "#64748b",  # hyperscalers / pre-IPO
}

STRATEGY_LABELS: Final[dict[str, str]] = {
    "ema_pullback": "EMA",
    "ath_pullback": "ATH",
    "consolidation_breakout": "FLAG",
    "ipo_base": "IPO",
}

# Status -> (emoji marker, short label). Used to summarize a ticker's signals.
STATUS_DISPLAY: Final[dict[str, tuple[str, str]]] = {
    # EMA pullback
    "AT_21_EMA": ("🟢", "at 21 EMA"),
    "AT_9_EMA": ("🟢", "at 9 EMA"),
    "APPROACHING_9": ("🟡", "→ 9 EMA"),
    "APPROACHING_21": ("🟡", "→ 21 EMA"),
    "EXTENDED": ("⚪", "extended"),
    "NEUTRAL": ("⚪", "neutral"),
    "BELOW_21_EMA": ("🔴", "below 21 EMA"),
    # ATH pullback
    "AT_ATH": ("🔵", "at ATH"),
    "MINOR_PULLBACK": ("🟢", "minor dip"),
    "ENTRY_ZONE": ("🟢", "entry zone"),
    "DEEP_PULLBACK": ("🟠", "deep dip"),
    "CORRECTION": ("🔴", "correction"),
    # consolidation
    "CONSOLIDATING": ("🔵", "consolidating"),
    "BREAKOUT": ("🟢", "breakout"),
    "BREAKDOWN": ("🔴", "breakdown"),
    "NO_PATTERN": ("⚪", "no base"),
    # IPO
    "IPO_FRESH": ("🔵", "IPO fresh"),
    "IPO_BASING": ("🔵", "IPO basing"),
    "IPO_BREAKOUT": ("🟢", "IPO breakout"),
    "IPO_FAILED": ("🔴", "IPO failed"),
    "INSUFFICIENT_DATA": ("⚪", "thin data"),
}

# Statuses that count as "approaching/at an entry" for value-chain summaries.
ENTRY_STATUSES: Final[frozenset[str]] = frozenset(
    {"AT_21_EMA", "AT_9_EMA", "ENTRY_ZONE", "BREAKOUT", "IPO_BREAKOUT"}
)


def stars(n: int) -> str:
    return "⭐" * n if n and n > 0 else ""


def status_label(status: str) -> str:
    emoji, label = STATUS_DISPLAY.get(status, ("", status))
    return f"{emoji} {label}".strip()


def layer_color(layer_key: str) -> str:
    return LAYER_COLORS.get(layer_key, "#888888")
