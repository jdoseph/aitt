"""Typed application configuration.

All settings load from environment variables (prefix ``AITT_``) or an optional
``.env`` file, falling back to the defaults defined here. Nothing in the codebase
should hardcode a threshold, path, or ticker — read it from :data:`settings`.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root = three levels up from this file (src/core/config.py -> project/).
PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Strongly-typed config for the tracker.

    Resolved architecture decisions (2026-05-29): agent runs on a single laptop,
    yfinance-only data, daily-close evaluation cadence, localhost dashboard.
    """

    model_config = SettingsConfigDict(
        env_prefix="AITT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- paths ---
    data_dir: Path = Field(default=Path("data"))
    db_path: Path = Field(default=Path("data/tracker.db"))
    watchlist_path: Path = Field(default=Path("src/core/watchlist.yaml"))

    # --- data layer ---
    history_bars: int = 200
    data_source: str = "yfinance"
    fetch_max_retries: int = 3
    fetch_retry_backoff_sec: float = 2.0

    # --- Strategy 1: EMA pullback ---
    ema_extended_pct: float = 8.0
    ema_approaching_9_pct: float = 2.0
    ema_approaching_21_pct: float = 3.0
    use_trend_filter: bool = False  # Q5: only alert when price > 50 EMA
    ema_require_volume: bool = False  # Q6: require above-avg volume on touch

    # --- Strategy 2: consolidation breakout ---
    consolidation_range_pct: float = 8.0
    consolidation_min_days: int = 10
    breakout_volume_mult: float = 1.5

    # --- Strategy 3: ATH pullback (pullback % below ATH defines the bands) ---
    # AT_ATH: <=at | MINOR: at..entry_low | ENTRY_ZONE: entry_low..entry_high
    # DEEP: entry_high..deep | CORRECTION: >deep
    ath_at_pct: float = 1.0
    ath_entry_low_pct: float = 5.0
    ath_entry_high_pct: float = 10.0
    ath_deep_pct: float = 20.0
    ath_freshness_days: int = 30

    # --- Strategy 4: IPO base ---
    ipo_max_history_days: int = 60
    ipo_initial_high_days: int = 5
    ipo_fresh_days: int = 5
    ipo_failed_drawdown_pct: float = 25.0

    # --- indicators ---
    volume_avg_window: int = 20

    # --- Session 7: setup quality scorecard ---
    min_risk_reward: float = 2.0
    earnings_buffer_days: int = 5
    rs_lookback: int = 20
    rs_benchmarks: list[str] = Field(default_factory=lambda: ["SPY", "QQQ", "SMH"])
    resistance_lookback: int = 60
    swing_pivot_k: int = 3  # bars each side that define a swing high/low
    low_headroom_pct: float = 3.0
    fallback_stop_pct: float = 8.0  # used when no swing-low support is found
    breadth_healthy_pct: float = 0.5  # >=50% of names bullish => healthy tape
    leading_layers_top_n: int = 3
    enable_scorecard: bool = True

    # --- Session 8: evidence layer (historical edge + catalysts) ---
    enable_backtest: bool = True
    backtest_history_period: str = "3y"
    backtest_history_bars: int = 780  # ~3 years of trading days to fetch for replay
    backtest_horizons: list[int] = Field(default_factory=lambda: [5, 10, 20])
    backtest_primary_horizon: int = 20
    backtest_min_occurrences: int = 5
    backtest_refresh_days: int = 7
    backtest_win_pass_pct: float = 60.0
    backtest_win_warn_pct: float = 50.0
    news_days: int = 7
    news_max_items: int = 5

    # --- alerts ---
    min_confidence_stars: int = 1
    alert_desktop: bool = True
    alert_console: bool = True

    # --- scheduler (daily-close cadence) ---
    market_tz: str = "America/New_York"
    eod_eval_hhmm: str = "16:15"

    # --- logging ---
    log_level: str = "INFO"

    @field_validator("data_dir", "db_path", "watchlist_path", mode="after")
    @classmethod
    def _anchor_to_project_root(cls, value: Path) -> Path:
        """Resolve relative paths against the project root so the cwd doesn't matter."""
        return value if value.is_absolute() else (PROJECT_ROOT / value)

    @property
    def eod_eval_hour(self) -> int:
        return int(self.eod_eval_hhmm.split(":")[0])

    @property
    def eod_eval_minute(self) -> int:
        return int(self.eod_eval_hhmm.split(":")[1])

    def ensure_dirs(self) -> None:
        """Create the data directory if missing (idempotent)."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton Settings instance."""
    return Settings()


# Module-level convenience handle.
settings: Settings = get_settings()
