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
from typing import Any, Optional, Sequence

import pandas as pd
from sqlalchemy import UniqueConstraint
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Session, SQLModel, col, create_engine, select

from src.core.config import settings


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
