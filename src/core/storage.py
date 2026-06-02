"""SQLite persistence via SQLModel.

Three tables:
  * ``prices``  — daily OHLCV, keyed by (ticker, date); upserts are idempotent.
  * ``signals`` — one row per (ticker, date, strategy); re-evaluating a day
                  updates the row rather than duplicating it.
  * ``alerts``  — fired alerts with an acknowledged flag.

The agent (writer) and dashboard (reader) share one DB file. Use :class:`Storage`
for a file-backed DB, or :meth:`Storage.in_memory` for tests.
"""

from __future__ import annotations

import json
from datetime import date as Date
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Sequence

import pandas as pd
from sqlalchemy import UniqueConstraint
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Session, SQLModel, col, create_engine, select

from src.core.config import settings

if TYPE_CHECKING:
    from src.core.portfolio import PaperPortfolio


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Tables
# --------------------------------------------------------------------------- #
class PriceBar(SQLModel, table=True):
    """One daily candle. Composite PK (ticker, date) makes upserts idempotent."""

    __tablename__ = "prices"

    ticker: str = Field(primary_key=True)
    date: Date = Field(primary_key=True)
    open: float
    high: float
    low: float
    close: float
    volume: float


class SignalRecord(SQLModel, table=True):
    """A strategy's classification of a ticker on a given date."""

    __tablename__ = "signals"
    __table_args__ = (UniqueConstraint("ticker", "date", "strategy", name="uq_signal"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    ticker: str = Field(index=True)
    date: Date = Field(index=True)
    strategy: str = Field(index=True)
    status: str
    details: str = ""  # JSON blob
    confidence: int = 0  # 0-3 stars
    patterns: str = ""  # JSON list of detected pattern names
    created_at: datetime = Field(default_factory=_utcnow)


class BacktestStat(SQLModel, table=True):
    """Cached historical win-rate for a (ticker, strategy, status, horizon)."""

    __tablename__ = "backtest_stats"

    ticker: str = Field(primary_key=True)
    strategy: str = Field(primary_key=True)
    status: str = Field(primary_key=True)
    horizon: int = Field(primary_key=True)
    n: int = 0
    wins: int = 0
    win_rate: float = 0.0  # percent
    avg_return: float = 0.0  # percent
    computed_at: datetime = Field(default_factory=_utcnow)


class DossierRecord(SQLModel, table=True):
    """A per-ticker trade due-diligence dossier for a given day (Session 9)."""

    __tablename__ = "dossiers"

    ticker: str = Field(primary_key=True)
    date: Date = Field(primary_key=True)
    grade: str = ""
    strongest_bull: str = ""
    strongest_bear: str = ""
    summary: str = ""  # JSON blob from Dossier.to_summary()
    created_at: datetime = Field(default_factory=_utcnow)


class RegimeRecord(SQLModel, table=True):
    """The market-regime label for a given cycle/day (Session 10)."""

    __tablename__ = "regime"

    date: Date = Field(primary_key=True)
    label: str = ""  # RISK_ON | NEUTRAL | RISK_OFF
    flags: str = ""  # JSON {symbol: above_50ema}
    summary: str = ""
    created_at: datetime = Field(default_factory=_utcnow)


class DailyScore(SQLModel, table=True):
    """A ticker's composite score + cross-sectional rank for a day (Session 11)."""

    __tablename__ = "daily_scores"

    ticker: str = Field(primary_key=True)
    date: Date = Field(primary_key=True)
    score: float = 0.0  # 0-100 composite
    rank: int = 0  # 1 = best that day
    n: int = 0  # cohort size
    rs_percentile: float = 0.0
    created_at: datetime = Field(default_factory=_utcnow)


class LayerStrengthRecord(SQLModel, table=True):
    """Per-layer 0-100 strength for a day (Session 11) — powers rotation deltas."""

    __tablename__ = "layer_strength"

    date: Date = Field(primary_key=True)
    layer: str = Field(primary_key=True)
    strength: float = 0.0
    created_at: datetime = Field(default_factory=_utcnow)


class PortfolioState(SQLModel, table=True):
    """The current paper-portfolio state (singleton row id=1) — Session 13."""

    __tablename__ = "portfolio"

    id: int = Field(default=1, primary_key=True)
    cash: float = 0.0
    positions: str = ""  # JSON: [{ticker, shares, entry}]
    updated_at: datetime = Field(default_factory=_utcnow)


class PortfolioSnapshot(SQLModel, table=True):
    """A per-day paper-portfolio snapshot for the NAV-vs-VOO history (Session 13)."""

    __tablename__ = "portfolio_history"

    date: Date = Field(primary_key=True)
    nav: float = 0.0
    exposure: float = 0.0  # 0-1 invested fraction
    regime: str = ""  # RISK_ON | NEUTRAL | RISK_OFF
    weights: str = ""  # JSON {ticker: weight}
    suggestions: str = ""  # JSON list of rebalance suggestion strings
    benchmark_value: float = 0.0  # benchmark (VOO) close — normalized for the overlay
    created_at: datetime = Field(default_factory=_utcnow)


class PaperTrade(SQLModel, table=True):
    """One simulated trade in the autonomous paper engine (Session 15).

    Lifecycle: PENDING (queued at daily close) → OPEN (filled at next open) →
    CLOSED (stop/target/daily-exit). ``signal_snapshot_json`` freezes the full
    decision state at queue time so the trade journal can show *why* it opened.
    All fake money — never routed to a broker.
    """

    __tablename__ = "paper_trades"

    trade_id: Optional[int] = Field(default=None, primary_key=True)
    ticker: str = Field(index=True)
    strategy: str = ""
    entry_signal_id: Optional[int] = None
    status: str = Field(default="PENDING", index=True)  # PENDING | OPEN | CLOSED
    # entry
    entry_date: Optional[Date] = None
    entry_price: float = 0.0  # fill incl. slippage
    entry_slippage_bps: float = 0.0
    # exit
    exit_date: Optional[Date] = None
    exit_price: float = 0.0  # fill incl. slippage
    exit_slippage_bps: float = 0.0
    exit_reason: str = ""  # EXIT_STOP | EXIT_TARGET | EXIT_EMA | EXIT_REGIME | ...
    pending_exit_reason: str = ""  # a daily exit queued for next open (while still OPEN)
    # sizing / levels
    shares: float = 0.0
    cost_basis: float = 0.0  # planned $ at PENDING; actual shares*entry at OPEN
    stop_price: float = 0.0
    target_price: float = 0.0
    # outcome
    pnl_dollars: float = 0.0
    pnl_pct: float = 0.0
    holding_days: int = 0
    gap_note: str = ""  # set when gap protection moved a fill off its expected price
    signal_snapshot_json: str = ""  # immutable decision snapshot
    created_at: datetime = Field(default_factory=_utcnow)


class CashbookEntry(SQLModel, table=True):
    """A daily paper-account snapshot for the NAV-vs-VOO equity curve (Session 15)."""

    __tablename__ = "portfolio_cashbook"

    date: Date = Field(primary_key=True)
    cash_start: float = 0.0
    cash_end: float = 0.0
    invested_value: float = 0.0
    total_nav: float = 0.0
    voo_nav: float = 0.0  # same-dollar VOO benchmark value
    voo_price: float = 0.0  # raw VOO close (lets the curve re-index from any start)
    regime: str = ""
    exposure_pct: float = 0.0
    created_at: datetime = Field(default_factory=_utcnow)


class OptionTrade(SQLModel, table=True):
    """One simulated long-call trade in the options engine (Session 16).

    Lifecycle PENDING→OPEN→CLOSED mirrors PaperTrade. Premiums are per-share;
    P&L = (exit_premium - entry_premium) * contracts * multiplier. ``price_source``
    records whether the entry fill came from the live chain or the model.
    """

    __tablename__ = "option_trades"

    trade_id: Optional[int] = Field(default=None, primary_key=True)
    ticker: str = Field(index=True)
    strategy: str = ""
    status: str = Field(default="PENDING", index=True)  # PENDING | OPEN | CLOSED
    # contract
    option_type: str = "call"
    strike: float = 0.0
    expiry: Optional[Date] = None
    dte_at_entry: int = 0
    contracts: int = 0
    multiplier: int = 100
    entry_iv: float = 0.0
    entry_delta: float = 0.0
    price_source: str = ""  # "chain" | "model"
    # entry
    entry_date: Optional[Date] = None
    entry_premium: float = 0.0  # per share, incl. slippage
    underlying_entry: float = 0.0
    # exit
    exit_date: Optional[Date] = None
    exit_premium: float = 0.0
    exit_reason: str = ""
    pending_exit_reason: str = ""
    underlying_exit: float = 0.0
    # levels carried from the dossier (on the underlying) + premium-based guards
    underlying_stop: float = 0.0
    underlying_target: float = 0.0
    tp_premium: float = 0.0  # absolute premium take-profit level
    sl_premium: float = 0.0  # absolute premium stop level
    # accounting
    cost_basis: float = 0.0  # contracts * entry_premium * multiplier (planned at PENDING)
    pnl_dollars: float = 0.0
    pnl_pct: float = 0.0
    holding_days: int = 0
    gap_note: str = ""
    signal_snapshot_json: str = ""
    created_at: datetime = Field(default_factory=_utcnow)


class OptionCashbook(SQLModel, table=True):
    """A daily options-account snapshot for the NAV-vs-VOO curve (Session 16)."""

    __tablename__ = "option_cashbook"

    date: Date = Field(primary_key=True)
    total_nav: float = 0.0
    voo_nav: float = 0.0
    voo_price: float = 0.0
    invested_value: float = 0.0
    regime: str = ""
    created_at: datetime = Field(default_factory=_utcnow)


class AlertRecord(SQLModel, table=True):
    """A fired alert (a noteworthy signal transition)."""

    __tablename__ = "alerts"

    id: Optional[int] = Field(default=None, primary_key=True)
    ticker: str = Field(index=True)
    date: Date = Field(index=True)
    strategy: str = Field(index=True)
    status: str = ""
    message: str = ""
    confidence: int = 0
    patterns: str = ""
    acknowledged: bool = Field(default=False, index=True)
    created_at: datetime = Field(default_factory=_utcnow)


# --------------------------------------------------------------------------- #
# Storage facade
# --------------------------------------------------------------------------- #
class Storage:
    """Thin facade over a SQLModel engine with domain-specific helpers."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        *,
        echo: bool = False,
        check_same_thread: bool = True,
    ) -> None:
        path = Path(db_path) if db_path is not None else settings.db_path
        path.parent.mkdir(parents=True, exist_ok=True)
        # The dashboard (Streamlit) shares one cached Storage across script
        # threads, so it opens with check_same_thread=False.
        self.engine = create_engine(
            f"sqlite:///{path}", echo=echo, connect_args={"check_same_thread": check_same_thread}
        )
        self.create_all()

    @classmethod
    def in_memory(cls, *, echo: bool = False) -> "Storage":
        """An isolated in-memory DB (single shared connection) — ideal for tests."""
        inst = cls.__new__(cls)
        inst.engine = create_engine(
            "sqlite://",
            echo=echo,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        inst.create_all()
        return inst

    def create_all(self) -> None:
        SQLModel.metadata.create_all(self.engine)

    def session(self) -> Session:
        return Session(self.engine)

    # --- prices ----------------------------------------------------------- #
    def upsert_prices(self, ticker: str, df: pd.DataFrame) -> int:
        """Insert/replace OHLCV rows for ``ticker``. Returns rows written.

        ``df`` is expected to be indexed by date with columns
        open/high/low/close/volume (the shape :func:`data.fetch_prices` returns).
        """
        ticker = ticker.upper()
        if df.empty:
            return 0
        with self.session() as s:
            for ts, row in df.iterrows():
                s.merge(
                    PriceBar(
                        ticker=ticker,
                        date=pd.Timestamp(ts).date(),
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=float(row["volume"]),
                    )
                )
            s.commit()
        return len(df)

    def get_prices(self, ticker: str) -> pd.DataFrame:
        """Return stored candles for ``ticker`` as a date-indexed OHLCV frame."""
        ticker = ticker.upper()
        with self.session() as s:
            rows = s.exec(
                select(PriceBar).where(PriceBar.ticker == ticker).order_by(col(PriceBar.date))
            ).all()
        if not rows:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        frame = pd.DataFrame(
            [
                {
                    "date": r.date,
                    "open": r.open,
                    "high": r.high,
                    "low": r.low,
                    "close": r.close,
                    "volume": r.volume,
                }
                for r in rows
            ]
        ).set_index("date")
        frame.index = pd.DatetimeIndex(frame.index, name="date")
        return frame

    def count_prices(self, ticker: str | None = None) -> int:
        with self.session() as s:
            stmt = select(PriceBar)
            if ticker is not None:
                stmt = stmt.where(PriceBar.ticker == ticker.upper())
            return len(s.exec(stmt).all())

    # --- signals ---------------------------------------------------------- #
    def record_signal(
        self,
        *,
        ticker: str,
        date: Date,
        strategy: str,
        status: str,
        details: dict[str, Any] | None = None,
        confidence: int = 0,
        patterns: Sequence[str] | None = None,
    ) -> SignalRecord:
        """Upsert a signal keyed by (ticker, date, strategy)."""
        ticker = ticker.upper()
        with self.session() as s:
            existing = s.exec(
                select(SignalRecord).where(
                    SignalRecord.ticker == ticker,
                    SignalRecord.date == date,
                    SignalRecord.strategy == strategy,
                )
            ).first()
            rec = existing or SignalRecord(ticker=ticker, date=date, strategy=strategy, status=status)
            rec.status = status
            rec.details = json.dumps(details or {})
            rec.confidence = confidence
            rec.patterns = json.dumps(list(patterns or []))
            rec.created_at = _utcnow()
            s.add(rec)
            s.commit()
            s.refresh(rec)
            return rec

    def get_signals(
        self, ticker: str | None = None, date: Date | None = None
    ) -> list[SignalRecord]:
        with self.session() as s:
            stmt = select(SignalRecord)
            if ticker is not None:
                stmt = stmt.where(SignalRecord.ticker == ticker.upper())
            if date is not None:
                stmt = stmt.where(SignalRecord.date == date)
            return list(s.exec(stmt.order_by(col(SignalRecord.confidence).desc())).all())

    def latest_signal(self, ticker: str, strategy: str) -> SignalRecord | None:
        """Most recent signal row for a (ticker, strategy) — used for transition detection."""
        with self.session() as s:
            return s.exec(
                select(SignalRecord)
                .where(SignalRecord.ticker == ticker.upper(), SignalRecord.strategy == strategy)
                .order_by(col(SignalRecord.date).desc())
            ).first()

    # --- alerts ----------------------------------------------------------- #
    def record_alert(
        self,
        *,
        ticker: str,
        date: Date,
        strategy: str,
        status: str = "",
        message: str = "",
        confidence: int = 0,
        patterns: Sequence[str] | None = None,
    ) -> AlertRecord:
        with self.session() as s:
            rec = AlertRecord(
                ticker=ticker.upper(),
                date=date,
                strategy=strategy,
                status=status,
                message=message,
                confidence=confidence,
                patterns=json.dumps(list(patterns or [])),
            )
            s.add(rec)
            s.commit()
            s.refresh(rec)
            return rec

    def get_alerts(self, acknowledged: bool | None = None) -> list[AlertRecord]:
        with self.session() as s:
            stmt = select(AlertRecord)
            if acknowledged is not None:
                stmt = stmt.where(AlertRecord.acknowledged == acknowledged)
            return list(s.exec(stmt.order_by(col(AlertRecord.created_at).desc())).all())

    def acknowledge_alert(self, alert_id: int) -> bool:
        with self.session() as s:
            rec = s.get(AlertRecord, alert_id)
            if rec is None:
                return False
            rec.acknowledged = True
            s.add(rec)
            s.commit()
            return True

    # --- dossiers --------------------------------------------------------- #
    def upsert_dossier(
        self,
        *,
        ticker: str,
        date: Date,
        grade: str,
        strongest_bull: str,
        strongest_bear: str,
        summary: dict[str, Any],
    ) -> DossierRecord:
        """Upsert the dossier keyed by (ticker, date)."""
        ticker = ticker.upper()
        with self.session() as s:
            rec = s.get(DossierRecord, (ticker, date)) or DossierRecord(ticker=ticker, date=date)
            rec.grade = grade
            rec.strongest_bull = strongest_bull
            rec.strongest_bear = strongest_bear
            rec.summary = json.dumps(summary)
            rec.created_at = _utcnow()
            s.merge(rec)
            s.commit()
            return rec

    def latest_dossier(self, ticker: str) -> DossierRecord | None:
        """Most recent dossier for a ticker (None if never graded)."""
        with self.session() as s:
            return s.exec(
                select(DossierRecord)
                .where(DossierRecord.ticker == ticker.upper())
                .order_by(col(DossierRecord.date).desc())
            ).first()

    # --- regime ----------------------------------------------------------- #
    def upsert_regime(
        self, *, date: Date, label: str, flags: dict[str, bool], summary: str
    ) -> RegimeRecord:
        """Upsert the market-regime label for a day (keyed by date)."""
        with self.session() as s:
            rec = s.get(RegimeRecord, date) or RegimeRecord(date=date)
            rec.label = label
            rec.flags = json.dumps(flags)
            rec.summary = summary
            rec.created_at = _utcnow()
            s.merge(rec)
            s.commit()
            return rec

    def latest_regime(self) -> RegimeRecord | None:
        """Most recent stored market-regime label (None if never computed)."""
        with self.session() as s:
            return s.exec(select(RegimeRecord).order_by(col(RegimeRecord.date).desc())).first()

    def recent_regime_labels(self, before: Date, limit: int) -> list[str]:
        """The ``limit`` most recent regime labels strictly before ``before``.

        Returned oldest → newest so the exposure dial can fold over them. Feeds
        the Session 13 hysteresis (the current cycle's label is appended by the
        caller before the prior cycle has been persisted).
        """
        with self.session() as s:
            rows = s.exec(
                select(RegimeRecord)
                .where(col(RegimeRecord.date) < before)
                .order_by(col(RegimeRecord.date).desc())
                .limit(limit)
            ).all()
        return [r.label for r in reversed(rows)]

    # --- daily composite scores (Session 11) ------------------------------ #
    def upsert_daily_score(
        self,
        *,
        ticker: str,
        date: Date,
        score: float,
        rank: int,
        n: int,
        rs_percentile: float = 0.0,
    ) -> DailyScore:
        """Upsert a ticker's composite score + rank, keyed by (ticker, date)."""
        ticker = ticker.upper()
        with self.session() as s:
            rec = s.get(DailyScore, (ticker, date)) or DailyScore(ticker=ticker, date=date)
            rec.score = score
            rec.rank = rank
            rec.n = n
            rec.rs_percentile = rs_percentile
            rec.created_at = _utcnow()
            s.merge(rec)
            s.commit()
            return rec

    def get_daily_scores(self, date: Date) -> list[DailyScore]:
        """All composite scores for a day, best rank first."""
        with self.session() as s:
            return list(
                s.exec(
                    select(DailyScore)
                    .where(DailyScore.date == date)
                    .order_by(col(DailyScore.rank))
                ).all()
            )

    def latest_daily_score(self, ticker: str) -> DailyScore | None:
        with self.session() as s:
            return s.exec(
                select(DailyScore)
                .where(DailyScore.ticker == ticker.upper())
                .order_by(col(DailyScore.date).desc())
            ).first()

    # --- layer strength + rotation (Session 11) --------------------------- #
    def upsert_layer_strength(self, *, date: Date, layer: str, strength: float) -> LayerStrengthRecord:
        """Upsert one layer's strength for a day, keyed by (date, layer)."""
        with self.session() as s:
            rec = s.get(LayerStrengthRecord, (date, layer)) or LayerStrengthRecord(
                date=date, layer=layer
            )
            rec.strength = strength
            rec.created_at = _utcnow()
            s.merge(rec)
            s.commit()
            return rec

    def get_layer_strength(self, date: Date) -> dict[str, float]:
        """All layer strengths on a given date as {layer: strength}."""
        with self.session() as s:
            rows = s.exec(
                select(LayerStrengthRecord).where(LayerStrengthRecord.date == date)
            ).all()
        return {r.layer: r.strength for r in rows}

    def prior_layer_strength(self, before: Date) -> dict[str, float]:
        """Layer strengths from the most recent day strictly before ``before``."""
        with self.session() as s:
            latest_row = s.exec(
                select(LayerStrengthRecord)
                .where(col(LayerStrengthRecord.date) < before)
                .order_by(col(LayerStrengthRecord.date).desc())
            ).first()
            if latest_row is None:
                return {}
            rows = s.exec(
                select(LayerStrengthRecord).where(
                    LayerStrengthRecord.date == latest_row.date
                )
            ).all()
        return {r.layer: r.strength for r in rows}

    # --- backtest stats --------------------------------------------------- #
    def get_backtest_stats(self, ticker: str, strategy: str, status: str) -> list[BacktestStat]:
        with self.session() as s:
            return list(
                s.exec(
                    select(BacktestStat).where(
                        BacktestStat.ticker == ticker.upper(),
                        BacktestStat.strategy == strategy,
                        BacktestStat.status == status,
                    )
                ).all()
            )

    def upsert_backtest_stats(self, stats: Sequence[BacktestStat]) -> int:
        with self.session() as s:
            for st in stats:
                st.ticker = st.ticker.upper()
                s.merge(st)
            s.commit()
        return len(stats)

    # --- paper portfolio (Session 13) ------------------------------------- #
    def load_portfolio(self) -> "PaperPortfolio":
        """Return the stored paper portfolio, or a fresh one seeded from config."""
        from src.core.portfolio import PaperPortfolio

        with self.session() as s:
            rec = s.get(PortfolioState, 1)
        if rec is None:
            return PaperPortfolio.empty()
        return PaperPortfolio.from_dict(
            {"cash": rec.cash, "positions": json.loads(rec.positions or "[]")}
        )

    def save_portfolio(self, portfolio: "PaperPortfolio") -> None:
        """Persist the current paper-portfolio state (singleton row)."""
        data = portfolio.to_dict()
        with self.session() as s:
            rec = s.get(PortfolioState, 1) or PortfolioState(id=1)
            rec.cash = float(data["cash"])
            rec.positions = json.dumps(data["positions"])
            rec.updated_at = _utcnow()
            s.merge(rec)
            s.commit()

    def upsert_portfolio_snapshot(
        self,
        *,
        date: Date,
        nav: float,
        exposure: float,
        regime: str,
        weights: dict[str, float],
        suggestions: Sequence[str],
        benchmark_value: float = 0.0,
    ) -> PortfolioSnapshot:
        """Upsert a day's NAV/exposure/holdings snapshot (keyed by date)."""
        with self.session() as s:
            rec = s.get(PortfolioSnapshot, date) or PortfolioSnapshot(date=date)
            rec.nav = nav
            rec.exposure = exposure
            rec.regime = regime
            rec.weights = json.dumps(weights)
            rec.suggestions = json.dumps(list(suggestions))
            rec.benchmark_value = benchmark_value
            rec.created_at = _utcnow()
            s.merge(rec)
            s.commit()
            return rec

    def get_portfolio_history(self) -> list[PortfolioSnapshot]:
        """All portfolio snapshots, oldest → newest (for the NAV-vs-VOO chart)."""
        with self.session() as s:
            return list(
                s.exec(select(PortfolioSnapshot).order_by(col(PortfolioSnapshot.date))).all()
            )

    def latest_portfolio_snapshot(self) -> PortfolioSnapshot | None:
        with self.session() as s:
            return s.exec(
                select(PortfolioSnapshot).order_by(col(PortfolioSnapshot.date).desc())
            ).first()

    # --- paper trades (Session 15) ---------------------------------------- #
    def add_paper_trade(self, trade: PaperTrade) -> PaperTrade:
        """Insert a new paper trade and return it with its assigned ``trade_id``."""
        trade.ticker = trade.ticker.upper()
        with self.session() as s:
            s.add(trade)
            s.commit()
            s.refresh(trade)
            return trade

    def update_paper_trade(self, trade: PaperTrade) -> PaperTrade:
        """Persist mutations to an existing paper trade (merge by primary key)."""
        with self.session() as s:
            merged = s.merge(trade)
            s.commit()
            s.refresh(merged)
            return merged

    def get_paper_trade(self, trade_id: int) -> PaperTrade | None:
        with self.session() as s:
            return s.get(PaperTrade, trade_id)

    def get_paper_trades(self, status: str | None = None) -> list[PaperTrade]:
        """All paper trades (optionally filtered by status), oldest → newest."""
        with self.session() as s:
            stmt = select(PaperTrade)
            if status is not None:
                stmt = stmt.where(PaperTrade.status == status)
            return list(s.exec(stmt.order_by(col(PaperTrade.trade_id))).all())

    # --- cashbook (Session 15) -------------------------------------------- #
    def upsert_cashbook(
        self,
        *,
        date: Date,
        cash_start: float,
        cash_end: float,
        invested_value: float,
        total_nav: float,
        voo_nav: float,
        regime: str,
        exposure_pct: float,
        voo_price: float = 0.0,
    ) -> CashbookEntry:
        """Upsert a day's cashbook snapshot (keyed by date)."""
        with self.session() as s:
            rec = s.get(CashbookEntry, date) or CashbookEntry(date=date)
            rec.cash_start = cash_start
            rec.cash_end = cash_end
            rec.invested_value = invested_value
            rec.total_nav = total_nav
            rec.voo_nav = voo_nav
            rec.voo_price = voo_price
            rec.regime = regime
            rec.exposure_pct = exposure_pct
            rec.created_at = _utcnow()
            s.merge(rec)
            s.commit()
            return rec

    def get_cashbook(self) -> list[CashbookEntry]:
        """All cashbook snapshots, oldest → newest (for the equity curve)."""
        with self.session() as s:
            return list(s.exec(select(CashbookEntry).order_by(col(CashbookEntry.date))).all())

    def latest_cashbook(self) -> CashbookEntry | None:
        with self.session() as s:
            return s.exec(
                select(CashbookEntry).order_by(col(CashbookEntry.date).desc())
            ).first()

    # --- option trades (Session 16) --------------------------------------- #
    def add_option_trade(self, trade: OptionTrade) -> OptionTrade:
        trade.ticker = trade.ticker.upper()
        with self.session() as s:
            s.add(trade)
            s.commit()
            s.refresh(trade)
            return trade

    def update_option_trade(self, trade: OptionTrade) -> OptionTrade:
        with self.session() as s:
            merged = s.merge(trade)
            s.commit()
            s.refresh(merged)
            return merged

    def get_option_trade(self, trade_id: int) -> OptionTrade | None:
        with self.session() as s:
            return s.get(OptionTrade, trade_id)

    def get_option_trades(self, status: str | None = None) -> list[OptionTrade]:
        with self.session() as s:
            stmt = select(OptionTrade)
            if status is not None:
                stmt = stmt.where(OptionTrade.status == status)
            return list(s.exec(stmt.order_by(col(OptionTrade.trade_id))).all())

    # --- option cashbook (Session 16) ------------------------------------- #
    def upsert_option_cashbook(
        self,
        *,
        date: Date,
        total_nav: float,
        voo_nav: float,
        invested_value: float,
        regime: str,
        voo_price: float = 0.0,
    ) -> OptionCashbook:
        with self.session() as s:
            rec = s.get(OptionCashbook, date) or OptionCashbook(date=date)
            rec.total_nav = total_nav
            rec.voo_nav = voo_nav
            rec.voo_price = voo_price
            rec.invested_value = invested_value
            rec.regime = regime
            rec.created_at = _utcnow()
            s.merge(rec)
            s.commit()
            return rec

    def get_option_cashbook(self) -> list[OptionCashbook]:
        with self.session() as s:
            return list(s.exec(select(OptionCashbook).order_by(col(OptionCashbook.date))).all())

    def latest_option_cashbook(self) -> OptionCashbook | None:
        with self.session() as s:
            return s.exec(
                select(OptionCashbook).order_by(col(OptionCashbook.date).desc())
            ).first()
