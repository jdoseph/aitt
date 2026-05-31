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
    # 260 ≈ one trading year, enough to meaningfully warm the 200 EMA (Session 9).
    history_bars: int = 260
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

    # --- Session 9: trade due diligence dossier ---
    # Above this much over the 50 EMA the setup reads as "chasing" (a bear point).
    ema_chasing_pct: float = 15.0
    # Span used for the *informational* market-regime line (QQQ/SMH vs own EMA).
    # The canonical RISK_ON/OFF gate (Session 10) uses its own 50-EMA span.
    regime_ema_span: int = 21
    # Profit-take levels suggested in the trade plan (percent above entry).
    profit_target_pcts: list[float] = Field(default_factory=lambda: [10.0, 15.0])
    # Cap on reasons shown per side of the bull/bear case.
    dossier_max_reasons: int = 6
    # Top N bear factors surfaced next to the grade in alerts.
    dossier_bear_in_alert: int = 2

    # --- Session 10: market-regime gate + automatic disqualifiers ---
    enable_regime_gate: bool = True
    # Canonical RISK_ON/OFF gate uses the 50-EMA (distinct from the Session 9
    # informational `regime_ema_span` of 21).
    regime_gate_ema_span: int = 50
    regime_risk_off_fails: int = 2  # >= this many of SPY/QQQ/SMH below 50 EMA => RISK_OFF
    # "suppress" => no notification; "downgrade" => alert fires but grade is capped.
    disqualifier_mode: str = "suppress"
    downgrade_cap_action: str = "MARGINAL"  # grade ceiling in downgrade mode
    dq_below_50ema: bool = True
    dq_earnings_days: int = 3  # suppress if earnings strictly within this many days
    dq_rs_below_market: bool = True
    dq_declining_volume: bool = True
    dq_min_rr: float = 0.0  # >0 enables: suppress if R:R below this
    risk_off_min_stars: int = 2  # entry alerts need >= this confidence in RISK_OFF

    # --- Session 12: deeper signals (institutional intent + trend context) ---
    # Accumulation (OBV / A-D / up-down volume / close-in-range).
    accumulation_lookback: int = 20
    accumulation_acc_score: float = 60.0  # >= this => "accumulation" label
    accumulation_dist_score: float = 40.0  # <= this => "distribution" label
    # Multi-timeframe (weekly trend alignment).
    weekly_ma_weeks: int = 30  # Weinstein's 30-week MA
    weekly_slope_lookback: int = 5  # weeks used to measure the MA slope
    weekly_slope_flat_pct: float = 0.5  # |MA % change| below this reads as flat
    # Weinstein stage classification reuses the weekly-MA knobs above.
    # ATR + crowding (volatility-normalized extension).
    atr_window: int = 14
    crowding_lookback: int = 20  # run-up window
    crowding_atr_extended: float = 8.0  # ATRs above 200 EMA that read as "fully extended"
    crowding_high_score: float = 70.0  # >= this 0-100 score => high crowding (a bear point)
    # AI-capex exposure default for watchlist entries that omit it (0-100).
    capex_exposure_default: int = 50

    # --- Session 11: composite score + cross-sectional ranking + rotation ---
    # Category weights for the 0-100 composite (should sum to 100; renormalized
    # over the categories that have data so an n/a category degrades gracefully).
    score_w_technical: float = 30.0
    score_w_rel_strength: float = 20.0
    score_w_volume_accum: float = 15.0
    score_w_regime: float = 10.0
    score_w_earnings: float = 10.0
    score_w_layer: float = 10.0
    score_w_catalyst: float = 5.0
    top_opportunities_n: int = 5  # names shown in the "Top opportunities today" panel
    rotation_lookback_days: int = 5  # window for the layer-strength rotation delta
    # Key value-chain leaders whose 50-EMA hold defines AI-thesis health.
    thesis_leaders: list[str] = Field(
        default_factory=lambda: ["NVDA", "AVGO", "VRT", "ANET", "MSFT", "MU"]
    )

    # --- Session 13: portfolio exposure management (paper-only) ---
    paper_start_balance: float = 5000.0
    # Regime → total invested fraction (0.0-1.0). The cash option the index lacks.
    target_exposure_on: float = 1.0
    target_exposure_neutral: float = 0.6
    target_exposure_off: float = 0.3
    # Hysteresis: a regime must persist this many trading days before the dial moves
    # (mandatory whipsaw guard — a one-day flip does NOT change exposure).
    regime_confirm_days: int = 3
    # Conviction sizing + concentration.
    max_positions: int = 6  # top-N by composite score that get weighted
    max_position_pct: float = 0.25  # concentration cap — no single name above this
    min_position_pct: float = 0.05  # weight floor — drop dust positions below this
    # Relative-strength rotation.
    exit_rank: int = 10  # a held name falling past this rank is cut
    min_grade: str = "DECENT"  # minimum scorecard action to enter a new name
    # Turnover / cost discipline.
    rebalance_cadence: str = "weekly"  # recompute targets on a schedule, not daily
    rebalance_threshold_pct: float = 0.03  # no-trade band — ignore drifts smaller than this
    portfolio_benchmark: str = "VOO"  # NAV is always benchmarked against the index
    enable_portfolio: bool = True

    # --- Session 14: walk-forward backtest vs VOO ---
    backtest_years: int = 5  # history window to replay
    cost_per_trade_bps: float = 10.0  # round-trip turnover cost (basis points)
    slippage_bps: float = 5.0  # additional slippage per unit of turnover (bps)
    trading_days_per_year: int = 252  # annualization factor for risk metrics

    # --- Session 15: autonomous paper trading engine ---
    enable_paper_trading: bool = True
    paper_budget: float = 5000.0  # fake-money budget the engine trades within
    paper_min_score: float = 55.0  # composite score floor to open a paper entry
    paper_min_grade: str = "DECENT"  # scorecard grade floor to open a paper entry
    min_position_size: float = 200.0  # smallest dollar position the engine will open
    base_position_pct: float = 0.20  # base sizing fraction (scaled by composite/100)
    # max_position_pct (0.25) from Session 13 is reused as the per-name budget cap.
    monitor_interval_minutes: int = 5  # intraday stop/target surveillance cadence
    time_stop_days: int = 30  # close a position held longer than this (EXIT_TIME)
    paper_exit_rank: int = 12  # held name falling past this rank rotates out (EXIT_ROTATION)
    paper_max_stop_pct: float = 0.0  # >0 enables a hard max stop this far below entry
    # Slippage tiers (basis points) keyed by liquidity, plus a volume adjustment.
    slippage_large_cap_usd: float = 50e9  # >= this market cap => large-cap tier
    slippage_mid_cap_usd: float = 10e9  # >= this (and < large) => mid-cap tier
    slippage_large_bps: float = 3.0
    slippage_mid_bps: float = 7.0
    slippage_small_bps: float = 12.0
    slippage_volatile_entry_bps: float = 20.0
    slippage_volatile_exit_bps: float = 25.0
    # Names treated as micro/volatile regardless of market cap (wider slippage).
    slippage_volatile_tickers: list[str] = Field(
        default_factory=lambda: ["RDW", "LUNR", "ASTS", "RKLB"]
    )
    volume_slippage_pct: float = 0.01  # position > this fraction of ADV adds extra bps
    volume_slippage_extra_bps: float = 5.0
    # Market-open fill + intraday monitor windows (market-local time).
    market_open_hhmm: str = "09:31"
    monitor_start_hhmm: str = "09:35"
    monitor_end_hhmm: str = "15:55"
    daily_summary_hhmm: str = "16:30"

    # --- alerts ---
    min_confidence_stars: int = 1
    alert_desktop: bool = True
    alert_console: bool = True

    # --- scheduler (daily-close cadence) ---
    market_tz: str = "America/New_York"
    eod_eval_hhmm: str = "16:15"

    # --- logging ---
    log_level: str = "INFO"
    # Rotating file sink for unattended (overnight/daily) runs. Set log_file to
    # an empty string to disable file logging and log to stderr only.
    log_file: Path = Field(default=Path("data/logs/agent.log"))
    log_rotation: str = "10 MB"  # loguru rotation trigger (size or time)
    log_retention: str = "14 days"  # how long rotated logs are kept

    @field_validator("data_dir", "db_path", "watchlist_path", "log_file", mode="after")
    @classmethod
    def _anchor_to_project_root(cls, value: Path) -> Path:
        """Resolve relative paths against the project root so the cwd doesn't matter.

        An empty path is left as-is (a sentinel meaning "no file logging").
        """
        if str(value) in ("", "."):
            return value
        return value if value.is_absolute() else (PROJECT_ROOT / value)

    @property
    def eod_eval_hour(self) -> int:
        return int(self.eod_eval_hhmm.split(":")[0])

    @property
    def eod_eval_minute(self) -> int:
        return int(self.eod_eval_hhmm.split(":")[1])

    @staticmethod
    def _hhmm(value: str) -> tuple[int, int]:
        h, m = value.split(":")
        return int(h), int(m)

    @property
    def market_open_hm(self) -> tuple[int, int]:
        return self._hhmm(self.market_open_hhmm)

    @property
    def monitor_start_hm(self) -> tuple[int, int]:
        return self._hhmm(self.monitor_start_hhmm)

    @property
    def monitor_end_hm(self) -> tuple[int, int]:
        return self._hhmm(self.monitor_end_hhmm)

    @property
    def daily_summary_hm(self) -> tuple[int, int]:
        return self._hhmm(self.daily_summary_hhmm)

    @property
    def file_logging_enabled(self) -> bool:
        """True when a real log-file path is configured (empty path disables it)."""
        return str(self.log_file) not in ("", ".")

    def ensure_dirs(self) -> None:
        """Create the data + log directories if missing (idempotent)."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if self.file_logging_enabled:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton Settings instance."""
    return Settings()


# Module-level convenience handle.
settings: Settings = get_settings()
