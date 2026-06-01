# Options Expression Layer (Session 16) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Trade the existing four strategies as long-call options instead of only shares, by adding an "expression" layer on top of the unchanged signal pipeline.

**Architecture:** Signals stay on the underlying (Sessions 1–15 untouched). A new `src/core/options/` package prices options with Black-Scholes (+ realized-vol fallback), selects a contract by target delta/DTE, and runs an `OptionBook` paper engine that mirrors the Session 15 `PaperBook`. Entry may use the live yfinance chain; all marks and the backtest use Black-Scholes. The stock and option books run side by side, selected by `trade_instrument` config.

**Tech Stack:** Python 3.12, SQLModel/SQLite, pandas, yfinance (live chain only), Streamlit, pytest, mypy --strict. Run tests with `./.venv/Scripts/python.exe -m pytest` and types with `./.venv/Scripts/python.exe -m mypy --strict src`.

**Conventions (match the existing codebase):**
- `from __future__ import annotations` at the top of every module.
- Type hints everywhere; `mypy --strict` must stay clean.
- No bare `except`; catch specific exceptions and log with `loguru`.
- Tests use `Storage.in_memory()` and the shared `storage` fixture in `tests/conftest.py`.
- Commit after each green task. Branch: `session-15-paper-trading` (already checked out).

---

## File Structure

**Create:**
- `src/core/options/__init__.py` — package marker
- `src/core/options/pricing.py` — Black-Scholes price + greeks + IV solver (pure)
- `src/core/options/vol.py` — realized-vol proxy
- `src/core/options/chain.py` — live yfinance chain fetch/parse (injectable)
- `src/core/options/contracts.py` — `OptionContract` + strike/expiry selection
- `src/core/options/option_trades.py` — `OptionBook` lifecycle
- `src/dashboard/pages/options.py` — Options dashboard page
- `tests/test_option_pricing.py`, `tests/test_option_vol.py`, `tests/test_option_contracts.py`, `tests/test_option_trades.py`, `tests/test_option_chain.py`, `tests/test_option_monitor.py`, `tests/test_option_storage.py`

**Modify:**
- `src/core/config.py` — Session 16 config block
- `src/core/storage.py` — `OptionTrade` + `OptionCashbook` tables + CRUD
- `src/agent/jobs.py` — option queue/fill/monitor/summary jobs + `trade_instrument` branching
- `src/agent/notify.py` — option trade notification formats
- `src/agent/scheduler.py` — branch the three paper jobs on `trade_instrument`
- `src/dashboard/app.py` — register the Options page
- `tests/test_dashboard.py` — add `options` to the render smoke list

---

## Task 1: Config block for the options layer

**Files:**
- Modify: `src/core/config.py` (insert after the Session 15 block, before `# --- alerts ---`)
- Test: `tests/test_option_config.py` (Create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_option_config.py`:

```python
"""Session 16 config defaults for the options layer."""

from __future__ import annotations

from src.core.config import Settings


def test_options_config_defaults() -> None:
    s = Settings()
    assert s.trade_instrument == "both"
    assert s.enable_options is True
    assert s.option_target_delta == 0.60
    assert s.option_target_dte == 45
    assert s.option_min_dte_exit == 21
    assert s.option_tp_pct == 50.0
    assert s.option_sl_pct == 50.0
    assert s.option_structure == "long_call"
    assert s.risk_free_rate == 0.04
    assert s.option_iv_premium_mult == 1.1
    assert s.realized_vol_window == 20
    assert s.option_slippage_bps_model == 50.0
    assert s.option_chain_min_oi == 10
    assert s.option_multiplier == 100
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_option_config.py -q`
Expected: FAIL with `AttributeError` (e.g. `'Settings' object has no attribute 'trade_instrument'`).

- [ ] **Step 3: Add the config block**

In `src/core/config.py`, insert this block immediately before the `    # --- alerts ---` line:

```python
    # --- Session 16: options expression layer ---
    # "stock" trades only the S15 share book, "option" only the option book,
    # "both" runs them in parallel against the same signals.
    trade_instrument: str = "both"  # "stock" | "option" | "both"
    enable_options: bool = True
    option_structure: str = "long_call"  # only long calls in this session
    option_target_delta: float = 0.60  # strike nearest this delta (slightly ITM)
    option_target_dte: int = 45  # expiry nearest this many days to expiration
    option_min_dte_exit: int = 21  # close at/under this DTE (theta/gamma cliff guard)
    option_tp_pct: float = 50.0  # take profit at +this% of entry premium
    option_sl_pct: float = 50.0  # stop at -this% of entry premium
    risk_free_rate: float = 0.04  # annualized, for Black-Scholes
    option_iv_premium_mult: float = 1.1  # realized-vol proxy is scaled by this
    realized_vol_window: int = 20  # trading days for the realized-vol estimate
    option_slippage_bps_model: float = 50.0  # slippage when a fill is model-priced
    option_chain_min_oi: int = 10  # min open interest for a live chain to be "usable"
    option_multiplier: int = 100  # shares per contract
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_option_config.py -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add src/core/config.py tests/test_option_config.py
git commit -m "feat(options): Session 16 config block"
```

---

## Task 2: Black-Scholes pricing + greeks + IV solver

**Files:**
- Create: `src/core/options/__init__.py`
- Create: `src/core/options/pricing.py`
- Test: `tests/test_option_pricing.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_option_pricing.py`:

```python
"""Black-Scholes price, greeks, and IV solver (Session 16)."""

from __future__ import annotations

import math

import pytest

from src.core.options import pricing as p


def test_bs_call_price_known_value() -> None:
    # S=100, K=100, T=1y, r=0, sigma=0.20 -> ~7.9656 (textbook ATM value).
    price = p.bs_price(100.0, 100.0, 1.0, 0.0, 0.20, call=True)
    assert price == pytest.approx(7.9656, abs=1e-3)


def test_put_call_parity() -> None:
    S, K, T, r, sig = 100.0, 90.0, 0.5, 0.03, 0.25
    call = p.bs_price(S, K, T, r, sig, call=True)
    put = p.bs_price(S, K, T, r, sig, call=False)
    # C - P == S - K*exp(-rT)
    assert call - put == pytest.approx(S - K * math.exp(-r * T), abs=1e-9)


def test_call_delta_in_unit_interval_and_itm_above_half() -> None:
    g = p.bs_greeks(110.0, 100.0, 0.5, 0.03, 0.25, call=True)
    assert 0.5 < g["delta"] < 1.0
    assert g["theta"] < 0.0  # long option bleeds time value
    assert g["vega"] > 0.0


def test_zero_time_price_is_intrinsic() -> None:
    assert p.bs_price(120.0, 100.0, 0.0, 0.03, 0.25, call=True) == pytest.approx(20.0)
    assert p.bs_price(90.0, 100.0, 0.0, 0.03, 0.25, call=True) == pytest.approx(0.0)


def test_implied_vol_round_trip() -> None:
    S, K, T, r, sig = 100.0, 105.0, 0.4, 0.02, 0.35
    price = p.bs_price(S, K, T, r, sig, call=True)
    solved = p.implied_vol(price, S, K, T, r, call=True)
    assert solved == pytest.approx(0.35, abs=1e-3)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_option_pricing.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.core.options'`.

- [ ] **Step 3: Write the implementation**

Create `src/core/options/__init__.py` (empty):

```python
"""Options expression layer (Session 16)."""
```

Create `src/core/options/pricing.py`:

```python
"""Black-Scholes pricing, greeks, and an implied-vol solver (Session 16).

Pure functions, no I/O. ``T`` is in years; ``sigma``/``r`` are annualized.
Greeks are per-1.0-of-underlying and per-1-year for theta (callers convert to
per-day for display). Used for every option mark and the entire backtest; the
live chain is only consulted at entry (see chain.py).
"""

from __future__ import annotations

import math


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _d1_d2(S: float, K: float, T: float, r: float, sigma: float) -> tuple[float, float]:
    vol_t = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / vol_t
    return d1, d1 - vol_t


def bs_price(S: float, K: float, T: float, r: float, sigma: float, *, call: bool = True) -> float:
    """Black-Scholes price. Degenerate inputs (T<=0 or sigma<=0) return intrinsic."""
    if T <= 0.0 or sigma <= 0.0 or S <= 0.0 or K <= 0.0:
        intrinsic = (S - K) if call else (K - S)
        return max(0.0, intrinsic)
    d1, d2 = _d1_d2(S, K, T, r, sigma)
    if call:
        return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
    return K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def bs_greeks(
    S: float, K: float, T: float, r: float, sigma: float, *, call: bool = True
) -> dict[str, float]:
    """Delta, gamma, vega (per 1.00 vol), theta (per year), rho. Intrinsic edge -> zeros."""
    if T <= 0.0 or sigma <= 0.0 or S <= 0.0 or K <= 0.0:
        delta = (1.0 if S > K else 0.0) if call else (-1.0 if S < K else 0.0)
        return {"delta": delta, "gamma": 0.0, "vega": 0.0, "theta": 0.0, "rho": 0.0}
    d1, d2 = _d1_d2(S, K, T, r, sigma)
    pdf = _norm_pdf(d1)
    gamma = pdf / (S * sigma * math.sqrt(T))
    vega = S * pdf * math.sqrt(T)
    if call:
        delta = _norm_cdf(d1)
        theta = -(S * pdf * sigma) / (2.0 * math.sqrt(T)) - r * K * math.exp(-r * T) * _norm_cdf(d2)
        rho = K * T * math.exp(-r * T) * _norm_cdf(d2)
    else:
        delta = _norm_cdf(d1) - 1.0
        theta = -(S * pdf * sigma) / (2.0 * math.sqrt(T)) + r * K * math.exp(-r * T) * _norm_cdf(-d2)
        rho = -K * T * math.exp(-r * T) * _norm_cdf(-d2)
    return {"delta": delta, "gamma": gamma, "vega": vega, "theta": theta, "rho": rho}


def implied_vol(
    price: float, S: float, K: float, T: float, r: float, *, call: bool = True,
    lo: float = 1e-4, hi: float = 5.0, tol: float = 1e-6, max_iter: int = 100,
) -> float | None:
    """Solve for sigma via bisection (robust). None if the price is below intrinsic."""
    if T <= 0.0 or price <= 0.0:
        return None
    intrinsic = max(0.0, (S - K) if call else (K - S))
    if price < intrinsic - tol:
        return None
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        diff = bs_price(S, K, T, r, mid, call=call) - price
        if abs(diff) < tol:
            return mid
        if diff > 0.0:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_option_pricing.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add src/core/options/__init__.py src/core/options/pricing.py tests/test_option_pricing.py
git commit -m "feat(options): Black-Scholes pricing + greeks + IV solver"
```

---

## Task 3: Realized-volatility proxy

**Files:**
- Create: `src/core/options/vol.py`
- Test: `tests/test_option_vol.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_option_vol.py`:

```python
"""Realized-volatility proxy (Session 16)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.core.options import vol


def _frame(closes: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="B")
    return pd.DataFrame({"close": closes}, index=idx)


def test_realized_vol_constant_series_is_zero() -> None:
    df = _frame([100.0] * 40)
    assert vol.realized_vol(df, window=20) == pytest.approx(0.0)


def test_realized_vol_is_annualized_and_scaled() -> None:
    rng = np.random.default_rng(0)
    # ~1% daily moves -> annualized ~ 0.01*sqrt(252) ~= 0.159, x1.1 premium.
    closes = [100.0]
    for r in rng.normal(0.0, 0.01, 260):
        closes.append(closes[-1] * (1.0 + r))
    sigma = vol.realized_vol(_frame(closes), window=30, premium_mult=1.1)
    assert 0.10 < sigma < 0.30


def test_realized_vol_thin_history_returns_fallback() -> None:
    df = _frame([100.0, 101.0])  # fewer than window+1 rows
    assert vol.realized_vol(df, window=20, fallback=0.5) == 0.5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_option_vol.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.core.options.vol'`.

- [ ] **Step 3: Write the implementation**

Create `src/core/options/vol.py`:

```python
"""Realized-volatility proxy used as the IV fallback and the backtest IV source."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.core.config import settings


def realized_vol(
    df: pd.DataFrame,
    *,
    window: int | None = None,
    premium_mult: float | None = None,
    fallback: float = 0.40,
) -> float:
    """Annualized stdev of the last ``window`` daily log returns, x ``premium_mult``.

    Returns ``fallback`` when there isn't enough history (< window+1 closes).
    """
    window = window if window is not None else settings.realized_vol_window
    premium_mult = (
        premium_mult if premium_mult is not None else settings.option_iv_premium_mult
    )
    if df is None or df.empty or "close" not in df.columns or len(df) < window + 1:
        return fallback
    closes = df["close"].to_numpy(dtype=float)[-(window + 1):]
    log_returns = np.diff(np.log(closes))
    daily = float(np.std(log_returns, ddof=1))
    return daily * float(np.sqrt(252.0)) * premium_mult
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_option_vol.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/core/options/vol.py tests/test_option_vol.py
git commit -m "feat(options): realized-volatility proxy"
```

---

## Task 4: OptionContract model + strike/expiry selection

**Files:**
- Create: `src/core/options/contracts.py`
- Test: `tests/test_option_contracts.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_option_contracts.py`:

```python
"""Contract model + strike/expiry selection (Session 16)."""

from __future__ import annotations

from datetime import date

import pandas as pd

from src.core.options.contracts import OptionContract, select_contract


def _frame(close: float, n: int = 60) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {"open": [close] * n, "high": [close] * n, "low": [close] * n,
         "close": [close] * n, "volume": [1_000_000] * n},
        index=idx,
    )


def test_select_contract_model_fallback_picks_dte_and_delta() -> None:
    # No live chain -> model path. ~0.60-delta call is slightly in-the-money,
    # so the chosen strike should sit below spot.
    df = _frame(100.0)
    c = select_contract(
        "NVDA", df, as_of=date(2024, 3, 1),
        chain=None, target_delta=0.60, target_dte=45, iv=0.30,
    )
    assert isinstance(c, OptionContract)
    assert c.source == "model"
    assert c.strike < 100.0  # ITM for ~0.60 delta
    assert 30 <= c.dte <= 60
    assert 0.45 < c.delta < 0.75


def test_select_contract_uses_live_chain_when_present() -> None:
    df = _frame(100.0)
    chain = {
        "expiry": date(2024, 4, 19),
        "calls": [
            {"strike": 95.0, "bid": 7.0, "ask": 7.4, "iv": 0.33, "open_interest": 500, "delta": 0.62},
            {"strike": 105.0, "bid": 2.0, "ask": 2.2, "iv": 0.31, "open_interest": 800, "delta": 0.40},
        ],
    }
    c = select_contract(
        "NVDA", df, as_of=date(2024, 3, 1),
        chain=chain, target_delta=0.60, target_dte=45, iv=0.33,
    )
    assert c.source == "chain"
    assert c.strike == 95.0  # nearest the 0.60 delta target
    assert c.expiry == date(2024, 4, 19)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_option_contracts.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.core.options.contracts'`.

- [ ] **Step 3: Write the implementation**

Create `src/core/options/contracts.py`:

```python
"""Option contract selection (Session 16).

A bullish signal expresses as a long call. We pick the expiry nearest a target
DTE and the strike nearest a target delta. With a live chain we use its quoted
deltas; without one we fall back to Black-Scholes deltas off a grid of strikes
around spot using the realized-vol IV. Pure given its inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as Date
from typing import Any

from src.core.options.pricing import bs_greeks


@dataclass(frozen=True)
class OptionContract:
    """A chosen call: strike/expiry plus the IV + delta and how it was priced."""

    option_type: str  # "call"
    strike: float
    expiry: Date
    dte: int
    iv: float
    delta: float
    source: str  # "chain" | "model"

    def to_summary(self) -> dict[str, Any]:
        return {
            "option_type": self.option_type,
            "strike": round(self.strike, 2),
            "expiry": self.expiry.isoformat(),
            "dte": self.dte,
            "iv": round(self.iv, 4),
            "delta": round(self.delta, 4),
            "source": self.source,
        }


def _from_chain(
    chain: dict[str, Any], spot: float, as_of: Date, target_delta: float, iv: float
) -> OptionContract:
    expiry: Date = chain["expiry"]
    dte = max(0, (expiry - as_of).days)
    best = min(chain["calls"], key=lambda c: abs(float(c.get("delta", 0.0)) - target_delta))
    return OptionContract(
        option_type="call",
        strike=float(best["strike"]),
        expiry=expiry,
        dte=dte,
        iv=float(best.get("iv", iv)),
        delta=float(best.get("delta", target_delta)),
        source="chain",
    )


def _from_model(
    spot: float, as_of: Date, target_delta: float, target_dte: int, iv: float, r: float
) -> OptionContract:
    expiry = as_of + _timedelta(target_dte)
    t_years = max(target_dte, 1) / 365.0
    # Scan strikes on a +/-40% grid in 0.5% steps; keep the one whose BS delta is
    # nearest the target.
    best_strike = spot
    best_delta = 1.0
    best_gap = 1e9
    step = max(spot * 0.005, 0.01)
    k = spot * 0.6
    while k <= spot * 1.4:
        delta = bs_greeks(spot, k, t_years, r, iv, call=True)["delta"]
        gap = abs(delta - target_delta)
        if gap < best_gap:
            best_gap, best_strike, best_delta = gap, k, delta
        k += step
    return OptionContract(
        option_type="call",
        strike=round(best_strike, 2),
        expiry=expiry,
        dte=target_dte,
        iv=iv,
        delta=best_delta,
        source="model",
    )


def _timedelta(days: int):  # tiny indirection so the import stays local + typed
    from datetime import timedelta

    return timedelta(days=days)


def select_contract(
    ticker: str,
    underlying_df: Any,
    *,
    as_of: Date,
    chain: dict[str, Any] | None,
    target_delta: float,
    target_dte: int,
    iv: float,
    risk_free_rate: float = 0.04,
) -> OptionContract:
    """Choose a long call by target delta + DTE; live chain if present, else model."""
    spot = float(underlying_df["close"].iloc[-1])
    if chain is not None and chain.get("calls"):
        return _from_chain(chain, spot, as_of, target_delta, iv)
    return _from_model(spot, as_of, target_delta, target_dte, iv, risk_free_rate)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_option_contracts.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/core/options/contracts.py tests/test_option_contracts.py
git commit -m "feat(options): contract model + strike/expiry selection"
```

---

## Task 5: Live option-chain fetch (injectable, fallback to None)

**Files:**
- Create: `src/core/options/chain.py`
- Test: `tests/test_option_chain.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_option_chain.py`:

```python
"""Live option-chain fetch + parse (Session 16)."""

from __future__ import annotations

from datetime import date

import pandas as pd

from src.core.options import chain as ch


class _FakeChain:
    def __init__(self, calls: pd.DataFrame) -> None:
        self.calls = calls
        self.puts = pd.DataFrame()


class _FakeTicker:
    def __init__(self, expiries: tuple[str, ...], calls: pd.DataFrame) -> None:
        self.options = expiries
        self._calls = calls

    def option_chain(self, expiry: str) -> _FakeChain:
        return _FakeChain(self._calls)


def test_fetch_chain_parses_calls() -> None:
    calls = pd.DataFrame(
        {"strike": [95.0, 100.0], "bid": [7.0, 4.0], "ask": [7.4, 4.3],
         "impliedVolatility": [0.33, 0.31], "openInterest": [500, 800]}
    )
    t = _FakeTicker(("2024-04-19", "2024-05-17"), calls)
    out = ch.fetch_chain("NVDA", target_dte=45, as_of=date(2024, 3, 1),
                         ticker_factory=lambda s: t, min_oi=10)
    assert out is not None
    assert out["expiry"] == date(2024, 4, 19)
    assert out["calls"][0]["strike"] == 95.0
    assert out["calls"][0]["iv"] == 0.33


def test_fetch_chain_thin_oi_returns_none() -> None:
    calls = pd.DataFrame(
        {"strike": [95.0], "bid": [7.0], "ask": [7.4],
         "impliedVolatility": [0.33], "openInterest": [1]}  # below min_oi
    )
    t = _FakeTicker(("2024-04-19",), calls)
    out = ch.fetch_chain("NVDA", target_dte=45, as_of=date(2024, 3, 1),
                         ticker_factory=lambda s: t, min_oi=10)
    assert out is None


def test_fetch_chain_no_expiries_returns_none() -> None:
    t = _FakeTicker((), pd.DataFrame())
    out = ch.fetch_chain("RDW", target_dte=45, as_of=date(2024, 3, 1),
                         ticker_factory=lambda s: t)
    assert out is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_option_chain.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.core.options.chain'`.

- [ ] **Step 3: Write the implementation**

Create `src/core/options/chain.py`:

```python
"""Live option-chain fetch via yfinance (Session 16) — forward-only.

This is the ONLY network piece of the options layer, and it is consulted only at
entry. It returns ``None`` whenever a usable chain isn't available (no expiries,
thin open interest, or any provider error), so callers fall back to the model.
``ticker_factory`` is injected in tests to stay offline.
"""

from __future__ import annotations

from datetime import date as Date
from datetime import datetime
from typing import Any, Callable

from loguru import logger

from src.core.config import settings


def _nearest_expiry(expiries: tuple[str, ...], target_dte: int, as_of: Date) -> str | None:
    best, best_gap = None, 10**9
    for e in expiries:
        try:
            d = datetime.strptime(e, "%Y-%m-%d").date()
        except ValueError:
            continue
        gap = abs((d - as_of).days - target_dte)
        if gap < best_gap:
            best_gap, best = gap, e
    return best


def fetch_chain(
    ticker: str,
    *,
    target_dte: int,
    as_of: Date,
    ticker_factory: Callable[[str], Any] | None = None,
    min_oi: int | None = None,
) -> dict[str, Any] | None:
    """Return ``{expiry, calls:[{strike,bid,ask,iv,open_interest}]}`` or None.

    A chain is "usable" only if at least one call has open interest >= ``min_oi``.
    """
    min_oi = min_oi if min_oi is not None else settings.option_chain_min_oi
    if ticker_factory is None:
        import yfinance as yf

        ticker_factory = yf.Ticker
    try:
        tk = ticker_factory(ticker)
        expiries = tuple(getattr(tk, "options", ()) or ())
        if not expiries:
            return None
        chosen = _nearest_expiry(expiries, target_dte, as_of)
        if chosen is None:
            return None
        oc = tk.option_chain(chosen)
        calls_df = oc.calls
        if calls_df is None or calls_df.empty:
            return None
        calls = []
        for _, row in calls_df.iterrows():
            oi = int(row.get("openInterest", 0) or 0)
            calls.append(
                {
                    "strike": float(row["strike"]),
                    "bid": float(row.get("bid", 0.0) or 0.0),
                    "ask": float(row.get("ask", 0.0) or 0.0),
                    "iv": float(row.get("impliedVolatility", 0.0) or 0.0),
                    "open_interest": oi,
                }
            )
        if not any(c["open_interest"] >= min_oi for c in calls):
            return None
        return {"expiry": datetime.strptime(chosen, "%Y-%m-%d").date(), "calls": calls}
    except Exception as exc:  # noqa: BLE001 - chain is best-effort; model is the fallback
        logger.warning("option-chain fetch failed for {}: {}", ticker, exc)
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_option_chain.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/core/options/chain.py tests/test_option_chain.py
git commit -m "feat(options): live option-chain fetch with None fallback"
```

---

## Task 6: Storage tables — OptionTrade + OptionCashbook + CRUD

**Files:**
- Modify: `src/core/storage.py` (add two table classes after `CashbookEntry`; add CRUD methods after `latest_cashbook`)
- Test: `tests/test_option_storage.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_option_storage.py`:

```python
"""Option-engine storage tables (Session 16)."""

from __future__ import annotations

from datetime import date

from src.core.storage import OptionTrade, Storage


def test_option_trade_roundtrip_and_status_filter(storage: Storage) -> None:
    pending = storage.add_option_trade(
        OptionTrade(
            ticker="nvda", strategy="composite", status="PENDING",
            option_type="call", strike=95.0, expiry=date(2024, 4, 19),
            dte_at_entry=45, contracts=2, multiplier=100, entry_iv=0.33,
            entry_delta=0.60, price_source="model", cost_basis=1480.0,
            underlying_stop=90.0, underlying_target=120.0,
            signal_snapshot_json='{"composite": 80}',
        )
    )
    assert pending.trade_id is not None
    assert pending.ticker == "NVDA"
    assert len(storage.get_option_trades(status="PENDING")) == 1
    assert storage.get_option_trades(status="OPEN") == []

    pending.status = "OPEN"
    pending.entry_premium = 7.40
    storage.update_option_trade(pending)
    reloaded = storage.get_option_trade(pending.trade_id)
    assert reloaded is not None and reloaded.status == "OPEN"
    assert reloaded.entry_premium == 7.40


def test_option_cashbook_upsert_idempotent(storage: Storage) -> None:
    storage.upsert_option_cashbook(
        date=date(2024, 1, 2), total_nav=5100.0, voo_nav=5050.0,
        invested_value=1500.0, regime="RISK_ON", voo_price=480.0,
    )
    storage.upsert_option_cashbook(
        date=date(2024, 1, 2), total_nav=5200.0, voo_nav=5050.0,
        invested_value=1600.0, regime="RISK_ON", voo_price=481.0,
    )
    hist = storage.get_option_cashbook()
    assert len(hist) == 1
    assert hist[0].total_nav == 5200.0
    assert storage.latest_option_cashbook() is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_option_storage.py -q`
Expected: FAIL with `ImportError: cannot import name 'OptionTrade'`.

- [ ] **Step 3: Add the tables**

In `src/core/storage.py`, immediately after the `class CashbookEntry(SQLModel, table=True):` block (before `class AlertRecord`), add:

```python
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
```

- [ ] **Step 4: Add the CRUD methods**

In `src/core/storage.py`, immediately after the `latest_cashbook` method, add (same indentation as the other `Storage` methods):

```python
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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_option_storage.py -q`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add src/core/storage.py tests/test_option_storage.py
git commit -m "feat(options): OptionTrade + OptionCashbook tables and CRUD"
```

---

## Task 7: OptionBook lifecycle (PENDING→OPEN→CLOSED, sizing, NAV)

**Files:**
- Create: `src/core/options/option_trades.py`
- Test: `tests/test_option_trades.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_option_trades.py`:

```python
"""OptionBook lifecycle + accounting (Session 16)."""

from __future__ import annotations

from datetime import date

import pytest

from src.core.options.contracts import OptionContract
from src.core.options.option_trades import OptionBook
from src.core.storage import Storage


@pytest.fixture
def book(storage: Storage) -> OptionBook:
    return OptionBook(storage, budget=5000.0)


def _contract() -> OptionContract:
    return OptionContract(
        option_type="call", strike=95.0, expiry=date(2024, 4, 19),
        dte=45, iv=0.33, delta=0.60, source="model",
    )


def _pending(book: OptionBook, ticker: str = "NVDA", premium: float = 7.0, planned: float = 1500.0):
    return book.create_pending(
        ticker=ticker, strategy="composite", contract=_contract(),
        snapshot={"composite": 80}, planned_dollars=planned,
        entry_premium_est=premium, underlying_stop=90.0, underlying_target=120.0,
    )


def test_create_pending_sizes_contracts_and_reserves_cash(book: OptionBook) -> None:
    t = _pending(book, premium=7.0, planned=1500.0)
    # 1500 / (7 * 100) = 2.14 -> floor 2 contracts; cost = 2*7*100 = 1400.
    assert t.contracts == 2
    assert t.cost_basis == pytest.approx(1400.0)
    assert book.available_cash() == pytest.approx(5000.0 - 1400.0)


def test_create_pending_skips_when_one_contract_exceeds_cap(storage: Storage) -> None:
    book = OptionBook(storage, budget=5000.0)  # cap = 0.25 * 5000 = 1250
    # premium 15 -> one contract costs 1500 > cap -> 0 contracts -> None.
    t = book.create_pending(
        ticker="NVDA", strategy="composite", contract=_contract(),
        snapshot={}, planned_dollars=2000.0, entry_premium_est=15.0,
        underlying_stop=90.0, underlying_target=120.0,
    )
    assert t is None
    assert book.pending_trades() == []


def test_execute_pending_fills_and_sets_premium_guards(book: OptionBook) -> None:
    t = _pending(book, premium=7.0)
    opened = book.execute_pending(t, fill_premium=7.40, on=date(2024, 3, 1), underlying=100.0)
    assert opened.status == "OPEN"
    assert opened.entry_premium == pytest.approx(7.40)
    assert opened.cost_basis == pytest.approx(2 * 7.40 * 100)
    assert opened.tp_premium == pytest.approx(7.40 * 1.5)   # +50%
    assert opened.sl_premium == pytest.approx(7.40 * 0.5)   # -50%


def test_close_trade_pnl_uses_multiplier(book: OptionBook) -> None:
    t = _pending(book, premium=7.0)
    book.execute_pending(t, fill_premium=7.0, on=date(2024, 3, 1), underlying=100.0)
    closed = book.close_trade(
        t, exit_premium=10.0, exit_reason="EXIT_TARGET", on=date(2024, 3, 20), underlying=115.0
    )
    assert closed.status == "CLOSED"
    # (10 - 7) * 2 contracts * 100 = 600
    assert closed.pnl_dollars == pytest.approx(600.0)
    assert closed.holding_days == 19


def test_current_nav_marks_open_positions(book: OptionBook) -> None:
    t = _pending(book, premium=7.0)
    book.execute_pending(t, fill_premium=7.0, on=date(2024, 3, 1), underlying=100.0)
    # mark each open contract at premium 9 -> MV = 2*9*100 = 1800; cash = 5000-1400=3600.
    nav = book.current_nav({t.trade_id: 9.0})
    assert nav == pytest.approx(3600.0 + 1800.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_option_trades.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.core.options.option_trades'`.

- [ ] **Step 3: Write the implementation**

Create `src/core/options/option_trades.py`:

```python
"""Option paper-book lifecycle + accounting (Session 16).

The options analogue of Session 15's ``PaperBook``. Positions are long calls held
in whole contracts (× ``multiplier`` shares). Premiums are per share; dollar P&L
multiplies by contracts × multiplier. Budget accounting mirrors PaperBook: spendable
cash = budget − OPEN/PENDING cost + realized P&L. All fake money.
"""

from __future__ import annotations

import json
import math
from datetime import date as Date
from typing import Any

from src.core.config import settings
from src.core.options.contracts import OptionContract
from src.core.storage import OptionTrade, Storage


class OptionBook:
    """The autonomous options paper account: lifecycle + budget + sizing + NAV."""

    def __init__(self, storage: Storage, *, budget: float | None = None) -> None:
        self.storage = storage
        self.budget = budget if budget is not None else settings.paper_budget

    # --- queries ---------------------------------------------------------- #
    def pending_trades(self) -> list[OptionTrade]:
        return self.storage.get_option_trades(status="PENDING")

    def open_trades(self) -> list[OptionTrade]:
        return self.storage.get_option_trades(status="OPEN")

    def closed_trades(self) -> list[OptionTrade]:
        return self.storage.get_option_trades(status="CLOSED")

    def has_active(self, ticker: str) -> bool:
        ticker = ticker.upper()
        return any(t.ticker == ticker for t in (*self.pending_trades(), *self.open_trades()))

    # --- cash accounting -------------------------------------------------- #
    def _committed_cost(self, *, include_pending: bool) -> float:
        statuses = ("OPEN", "PENDING") if include_pending else ("OPEN",)
        total = 0.0
        for status in statuses:
            total += sum(t.cost_basis for t in self.storage.get_option_trades(status=status))
        return total

    def _realized_pnl(self) -> float:
        return sum(t.pnl_dollars for t in self.closed_trades())

    def available_cash(self) -> float:
        cash = self.budget - self._committed_cost(include_pending=True) + self._realized_pnl()
        return max(0.0, cash)

    def _nav_cash(self) -> float:
        return self.budget - self._committed_cost(include_pending=False) + self._realized_pnl()

    def invested_value(self, marks: dict[int, float]) -> float:
        """Market value of OPEN positions; ``marks`` maps trade_id -> current premium."""
        total = 0.0
        for t in self.open_trades():
            prem = marks.get(t.trade_id or -1, t.entry_premium)
            total += prem * t.contracts * t.multiplier
        return total

    def current_nav(self, marks: dict[int, float]) -> float:
        return self._nav_cash() + self.invested_value(marks)

    def voo_nav(self, voo_start_price: float, voo_current_price: float) -> float:
        if voo_start_price <= 0:
            return self.budget
        return self.budget * (voo_current_price / voo_start_price)

    # --- sizing ----------------------------------------------------------- #
    def size_contracts(self, premium: float, planned_dollars: float) -> int:
        """Whole contracts affordable within the per-name cap and available cash."""
        if premium <= 0:
            return 0
        cap = min(settings.max_position_pct * self.budget, self.available_cash())
        budget_for_name = min(planned_dollars, cap)
        per_contract = premium * settings.option_multiplier
        return int(math.floor(budget_for_name / per_contract))

    # --- lifecycle -------------------------------------------------------- #
    def create_pending(
        self,
        *,
        ticker: str,
        strategy: str,
        contract: OptionContract,
        snapshot: dict[str, Any],
        planned_dollars: float,
        entry_premium_est: float,
        underlying_stop: float,
        underlying_target: float,
    ) -> OptionTrade | None:
        """Queue a PENDING long call; None when not even one contract fits the cap."""
        contracts = self.size_contracts(entry_premium_est, planned_dollars)
        if contracts < 1:
            return None
        cost = contracts * entry_premium_est * settings.option_multiplier
        trade = OptionTrade(
            ticker=ticker.upper(),
            strategy=strategy,
            status="PENDING",
            option_type=contract.option_type,
            strike=contract.strike,
            expiry=contract.expiry,
            dte_at_entry=contract.dte,
            contracts=contracts,
            multiplier=settings.option_multiplier,
            entry_iv=contract.iv,
            entry_delta=contract.delta,
            price_source=contract.source,
            cost_basis=cost,
            underlying_stop=underlying_stop,
            underlying_target=underlying_target,
            signal_snapshot_json=json.dumps({**snapshot, "contract": contract.to_summary()}),
        )
        return self.storage.add_option_trade(trade)

    def execute_pending(
        self, trade: OptionTrade, *, fill_premium: float, on: Date, underlying: float
    ) -> OptionTrade:
        """Fill a PENDING long call at ``fill_premium`` (already slippage-adjusted)."""
        trade.entry_premium = fill_premium
        trade.entry_date = on
        trade.underlying_entry = underlying
        trade.cost_basis = trade.contracts * fill_premium * trade.multiplier
        trade.tp_premium = fill_premium * (1.0 + settings.option_tp_pct / 100.0)
        trade.sl_premium = fill_premium * (1.0 - settings.option_sl_pct / 100.0)
        trade.status = "OPEN"
        return self.storage.update_option_trade(trade)

    def close_trade(
        self, trade: OptionTrade, *, exit_premium: float, exit_reason: str, on: Date,
        underlying: float, gap_note: str = "",
    ) -> OptionTrade:
        """Close an OPEN long call; P&L = (exit-entry) * contracts * multiplier."""
        trade.exit_premium = exit_premium
        trade.exit_date = on
        trade.exit_reason = exit_reason
        trade.pending_exit_reason = ""
        trade.underlying_exit = underlying
        trade.pnl_dollars = (exit_premium - trade.entry_premium) * trade.contracts * trade.multiplier
        cost = trade.entry_premium * trade.contracts * trade.multiplier
        trade.pnl_pct = (trade.pnl_dollars / cost * 100.0) if cost else 0.0
        if trade.entry_date is not None:
            trade.holding_days = (on - trade.entry_date).days
        trade.gap_note = gap_note
        trade.status = "CLOSED"
        return self.storage.update_option_trade(trade)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_option_trades.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add src/core/options/option_trades.py tests/test_option_trades.py
git commit -m "feat(options): OptionBook lifecycle + greeks-aware sizing + NAV"
```

---

## Task 8: Marking + exit evaluation helpers

**Files:**
- Modify: `src/core/options/option_trades.py` (add module-level `mark_premium` and `evaluate_exit` helpers after the `OptionBook` class)
- Test: `tests/test_option_monitor.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_option_monitor.py`:

```python
"""Option marking + whichever-first exit evaluation (Session 16)."""

from __future__ import annotations

from datetime import date

import pytest

from src.core.options.option_trades import evaluate_exit, mark_premium
from src.core.storage import OptionTrade


def _open_trade(**kw) -> OptionTrade:
    base = dict(
        ticker="NVDA", status="OPEN", option_type="call", strike=95.0,
        expiry=date(2024, 4, 19), contracts=2, multiplier=100, entry_iv=0.30,
        entry_premium=7.0, entry_date=date(2024, 3, 1), underlying_entry=100.0,
        underlying_stop=90.0, underlying_target=120.0,
        tp_premium=10.5, sl_premium=3.5,
    )
    base.update(kw)
    return OptionTrade(**base)


def test_mark_premium_uses_black_scholes() -> None:
    t = _open_trade()
    prem = mark_premium(t, underlying=100.0, on=date(2024, 3, 15), iv=0.30, risk_free_rate=0.04)
    assert prem > 5.0  # ITM call with ~35 DTE has real value


def test_exit_underlying_stop() -> None:
    t = _open_trade()
    reason = evaluate_exit(t, underlying=89.0, premium=4.0, on=date(2024, 3, 15))
    assert reason == "EXIT_STOP"


def test_exit_underlying_target() -> None:
    t = _open_trade()
    reason = evaluate_exit(t, underlying=121.0, premium=9.0, on=date(2024, 3, 15))
    assert reason == "EXIT_TARGET"


def test_exit_premium_take_profit() -> None:
    t = _open_trade()
    reason = evaluate_exit(t, underlying=110.0, premium=11.0, on=date(2024, 3, 15))
    assert reason == "EXIT_OPT_TP"


def test_exit_premium_stop() -> None:
    t = _open_trade()
    reason = evaluate_exit(t, underlying=96.0, premium=3.0, on=date(2024, 3, 15))
    assert reason == "EXIT_OPT_SL"


def test_exit_min_dte() -> None:
    t = _open_trade()
    # 21-day guard: on an as-of date within 21 days of the 2024-04-19 expiry.
    reason = evaluate_exit(t, underlying=100.0, premium=7.0, on=date(2024, 4, 5))
    assert reason == "EXIT_DTE"


def test_exit_expiry() -> None:
    t = _open_trade()
    reason = evaluate_exit(t, underlying=100.0, premium=7.0, on=date(2024, 4, 19))
    assert reason == "EXIT_EXPIRY"


def test_exit_stop_priority_over_target_when_both() -> None:
    t = _open_trade()
    # Degenerate: both stop and target appear satisfied -> stop wins.
    t.underlying_stop = 120.0
    t.underlying_target = 120.0
    reason = evaluate_exit(t, underlying=120.0, premium=9.0, on=date(2024, 3, 15))
    assert reason == "EXIT_STOP"


def test_no_exit_returns_empty() -> None:
    t = _open_trade()
    assert evaluate_exit(t, underlying=105.0, premium=8.0, on=date(2024, 3, 15)) == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_option_monitor.py -q`
Expected: FAIL with `ImportError: cannot import name 'evaluate_exit'`.

- [ ] **Step 3: Write the implementation**

Append to `src/core/options/option_trades.py` (after the `OptionBook` class):

```python
# --------------------------------------------------------------------------- #
# Marking + exit evaluation (module-level, pure)
# --------------------------------------------------------------------------- #
def mark_premium(
    trade: OptionTrade, *, underlying: float, on: Date, iv: float, risk_free_rate: float
) -> float:
    """Black-Scholes mark for an open call given today's underlying + IV.

    DTE is measured from ``on`` to expiry; at/after expiry the mark is intrinsic.
    """
    from src.core.options.pricing import bs_price

    if trade.expiry is None:
        return max(0.0, underlying - trade.strike)
    dte = (trade.expiry - on).days
    t_years = max(dte, 0) / 365.0
    return bs_price(underlying, trade.strike, t_years, risk_free_rate, iv, call=True)


def evaluate_exit(trade: OptionTrade, *, underlying: float, premium: float, on: Date) -> str:
    """Return the first-tripped exit reason (whichever-first), or '' to hold.

    Priority: underlying stop → underlying target → premium take-profit →
    premium stop → min-DTE guard → expiry.
    """
    if trade.underlying_stop and underlying <= trade.underlying_stop:
        return "EXIT_STOP"
    if trade.underlying_target and underlying >= trade.underlying_target:
        return "EXIT_TARGET"
    if trade.tp_premium and premium >= trade.tp_premium:
        return "EXIT_OPT_TP"
    if trade.sl_premium and premium <= trade.sl_premium:
        return "EXIT_OPT_SL"
    if trade.expiry is not None:
        dte = (trade.expiry - on).days
        if dte <= 0:
            return "EXIT_EXPIRY"
        if dte <= settings.option_min_dte_exit:
            return "EXIT_DTE"
    return ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_option_monitor.py -q`
Expected: PASS (9 passed).

- [ ] **Step 5: Commit**

```bash
git add src/core/options/option_trades.py tests/test_option_monitor.py
git commit -m "feat(options): BS marking + whichever-first exit evaluation"
```

---

## Task 9: Option premium pricing helper (hybrid: chain mid or model)

**Files:**
- Modify: `src/core/options/pricing.py` (add `entry_premium` helper at the end)
- Test: `tests/test_option_pricing.py` (add cases)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_option_pricing.py`:

```python
from datetime import date

from src.core.options.contracts import OptionContract


def _contract(source: str) -> OptionContract:
    return OptionContract(
        option_type="call", strike=95.0, expiry=date(2024, 4, 19),
        dte=45, iv=0.30, delta=0.60, source=source,
    )


def test_entry_premium_model_path_uses_black_scholes() -> None:
    c = _contract("model")
    prem, src = p.entry_premium(
        c, underlying=100.0, on=date(2024, 3, 5), chain=None, risk_free_rate=0.04
    )
    assert src == "model"
    assert prem > 5.0


def test_entry_premium_chain_path_uses_mid() -> None:
    c = _contract("chain")
    chain = {"expiry": date(2024, 4, 19),
             "calls": [{"strike": 95.0, "bid": 7.0, "ask": 7.4, "iv": 0.33, "open_interest": 500}]}
    prem, src = p.entry_premium(
        c, underlying=100.0, on=date(2024, 3, 5), chain=chain, risk_free_rate=0.04
    )
    assert src == "chain"
    assert prem == pytest.approx(7.2)  # (7.0 + 7.4)/2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_option_pricing.py -k entry_premium -q`
Expected: FAIL with `AttributeError: module 'src.core.options.pricing' has no attribute 'entry_premium'`.

- [ ] **Step 3: Write the implementation**

Append to `src/core/options/pricing.py`:

```python
def entry_premium(
    contract: Any,  # OptionContract (imported lazily to avoid a cycle)
    *,
    underlying: float,
    on: Any,  # datetime.date
    chain: dict[str, Any] | None,
    risk_free_rate: float,
) -> tuple[float, str]:
    """Entry premium per the hybrid rule: live chain mid if the strike is quoted,
    else Black-Scholes. Returns ``(premium, source)`` where source is chain|model.
    """
    if chain is not None and chain.get("calls"):
        for c in chain["calls"]:
            if abs(float(c["strike"]) - contract.strike) < 1e-9:
                bid, ask = float(c.get("bid", 0.0)), float(c.get("ask", 0.0))
                if bid > 0.0 and ask > 0.0:
                    return (bid + ask) / 2.0, "chain"
    dte = (contract.expiry - on).days if contract.expiry is not None else 0
    t_years = max(dte, 0) / 365.0
    return bs_price(underlying, contract.strike, t_years, risk_free_rate, contract.iv, call=True), "model"
```

Add `from typing import Any` to the imports at the top of `pricing.py` if not already present (it is not — add it).

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_option_pricing.py -q`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add src/core/options/pricing.py tests/test_option_pricing.py
git commit -m "feat(options): hybrid entry-premium helper (chain mid or model)"
```

---

## Task 10: Agent jobs — option queue / fill / monitor / summary

**Files:**
- Modify: `src/agent/jobs.py` (add an options job section after `daily_summary`/`_latest_close`, before the calendar guard; extend imports)
- Modify: `src/agent/notify.py` (add option notification formats)
- Test: `tests/test_option_jobs.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_option_jobs.py`:

```python
"""Option queueing + fill + monitor jobs (Session 16)."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from src.agent import jobs
from src.core.options.option_trades import OptionBook
from src.core.storage import Storage


def _seed_candidate(store: Storage, ticker: str, *, on: date, score: float, rank: int, grade: str) -> None:
    store.upsert_daily_score(ticker=ticker, date=on, score=score, rank=rank, n=10)
    store.upsert_dossier(
        ticker=ticker, date=on, grade=grade, strongest_bull="x", strongest_bear="y",
        summary={"trade_plan": {"stop": 90.0, "target": 120.0, "entry": 100.0}},
    )


def _price_df(close: float, n: int = 60) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame({"open": [close] * n, "high": [close] * n, "low": [close] * n,
                         "close": [close] * n, "volume": [1_000_000] * n}, index=idx)


def test_queue_option_entries_creates_pending() -> None:
    store = Storage.in_memory()
    on = date(2024, 3, 1)
    _seed_candidate(store, "NVDA", on=on, score=80, rank=1, grade="HIGH-QUALITY")
    store.upsert_prices("NVDA", _price_df(100.0))
    book = OptionBook(store, budget=5000.0)
    created = jobs.queue_option_entries(
        book, store, on=on, regime_label="RISK_ON",
        price_provider=lambda t: store.get_prices(t),
        chain_provider=lambda t, dte, as_of: None,  # force model path
    )
    assert [t.ticker for t in created] == ["NVDA"]
    pend = book.pending_trades()[0]
    assert pend.contracts >= 1
    assert pend.price_source == "model"


def test_queue_option_entries_suppressed_in_risk_off() -> None:
    store = Storage.in_memory()
    on = date(2024, 3, 1)
    _seed_candidate(store, "NVDA", on=on, score=90, rank=1, grade="HIGH-QUALITY")
    store.upsert_prices("NVDA", _price_df(100.0))
    book = OptionBook(store, budget=5000.0)
    created = jobs.queue_option_entries(
        book, store, on=on, regime_label="RISK_OFF",
        price_provider=lambda t: store.get_prices(t),
        chain_provider=lambda t, dte, as_of: None,
    )
    assert created == []


def test_execute_option_open_fills_pending() -> None:
    store = Storage.in_memory()
    on = date(2024, 3, 1)
    _seed_candidate(store, "NVDA", on=on, score=80, rank=1, grade="DECENT")
    store.upsert_prices("NVDA", _price_df(100.0))
    book = OptionBook(store, budget=5000.0)
    jobs.queue_option_entries(
        book, store, on=on, regime_label="RISK_ON",
        price_provider=lambda t: store.get_prices(t),
        chain_provider=lambda t, dte, as_of: None,
    )
    opened = jobs.execute_option_open(
        book, on=date(2024, 3, 4),
        underlying_provider=lambda t, d: 101.0,
        chain_provider=lambda t, dte, as_of: None,
    )
    assert len(opened) == 1
    assert opened[0].status == "OPEN"
    assert opened[0].entry_premium > 0.0


def test_monitor_option_positions_closes_on_target() -> None:
    store = Storage.in_memory()
    book = OptionBook(store, budget=5000.0)
    from src.core.options.contracts import OptionContract
    c = OptionContract(option_type="call", strike=95.0, expiry=date(2024, 4, 19),
                       dte=45, iv=0.30, delta=0.60, source="model")
    t = book.create_pending(ticker="NVDA", strategy="composite", contract=c, snapshot={},
                            planned_dollars=1500.0, entry_premium_est=7.0,
                            underlying_stop=90.0, underlying_target=120.0)
    book.execute_pending(t, fill_premium=7.0, on=date(2024, 3, 1), underlying=100.0)
    closed = jobs.monitor_option_positions(
        book, on=date(2024, 3, 15),
        underlying_provider=lambda t: 121.0,  # >= target
    )
    assert len(closed) == 1
    assert closed[0].exit_reason == "EXIT_TARGET"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_option_jobs.py -q`
Expected: FAIL with `AttributeError: module 'src.agent.jobs' has no attribute 'queue_option_entries'`.

- [ ] **Step 3: Extend imports in `src/agent/jobs.py`**

Add these imports near the other `src.core` imports at the top of `src/agent/jobs.py`:

```python
from src.core.options import chain as option_chain
from src.core.options import vol as option_vol
from src.core.options.contracts import select_contract
from src.core.options.option_trades import OptionBook, evaluate_exit, mark_premium
from src.core.options.pricing import entry_premium
from src.core.options.contracts import OptionContract  # noqa: F401 (used in annotations/tests)
```

Add a type alias near the top (after the existing `SlippageFn` line):

```python
ChainProvider = Callable[[str, int, Date], "dict[str, Any] | None"]
UnderlyingDateProvider = Callable[[str, Date], "float | None"]
UnderlyingProvider = Callable[[str], "float | None"]
PriceFrameProvider = Callable[[str], pd.DataFrame]
```

Ensure `from typing import Any` is imported in `jobs.py` (it is already used via `dict[str, Any]` in `queue_entries`; if missing, add it).

- [ ] **Step 4: Write the option jobs**

Insert into `src/agent/jobs.py` immediately after the `_latest_close` function (before the `# Trading-calendar guard` banner):

```python
# --------------------------------------------------------------------------- #
# Session 16 — options expression layer jobs
# --------------------------------------------------------------------------- #
def _default_chain_provider(ticker: str, dte: int, as_of: Date) -> dict[str, Any] | None:
    return option_chain.fetch_chain(ticker, target_dte=dte, as_of=as_of)


def queue_option_entries(
    book: OptionBook,
    store: Storage,
    *,
    on: Date,
    regime_label: str,
    price_provider: PriceFrameProvider,
    chain_provider: ChainProvider | None = None,
) -> list[OptionTrade]:
    """Queue PENDING long calls from the day's graded candidates (same gates as stock)."""
    if regime_label == "RISK_OFF":
        return []
    chain_provider = chain_provider or _default_chain_provider
    created: list[OptionTrade] = []
    for ds in store.get_daily_scores(on):
        if ds.score < settings.paper_min_score:
            continue
        if book.has_active(ds.ticker):
            continue
        dossier = store.latest_dossier(ds.ticker)
        if dossier is None or dossier.date != on or not _grade_ok(dossier.grade, settings.paper_min_grade):
            continue
        df = price_provider(ds.ticker)
        if df is None or df.empty:
            continue
        plan = json.loads(dossier.summary or "{}").get("trade_plan", {})
        stop = float(plan.get("stop") or 0.0)
        target = float(plan.get("target") or 0.0)
        chain = chain_provider(ds.ticker, settings.option_target_dte, on)
        iv = option_vol.realized_vol(df)
        if chain is not None and chain.get("calls"):
            atm = min(chain["calls"], key=lambda c: abs(float(c["strike"]) - float(df["close"].iloc[-1])))
            if atm.get("iv"):
                iv = float(atm["iv"])
        contract = select_contract(
            ds.ticker, df, as_of=on, chain=chain,
            target_delta=settings.option_target_delta,
            target_dte=settings.option_target_dte, iv=iv,
            risk_free_rate=settings.risk_free_rate,
        )
        est_prem, _ = entry_premium(
            contract, underlying=float(df["close"].iloc[-1]), on=on,
            chain=chain, risk_free_rate=settings.risk_free_rate,
        )
        # Fund each name up to the per-name cap; create_pending floors to whole
        # contracts and returns None if not even one contract fits.
        trade = book.create_pending(
            ticker=ds.ticker, strategy="composite", contract=contract,
            snapshot={"composite": ds.score, "rank": ds.rank, "grade": dossier.grade,
                      "regime": regime_label, "dossier": json.loads(dossier.summary or "{}")},
            planned_dollars=settings.max_position_pct * book.budget,
            entry_premium_est=est_prem, underlying_stop=stop, underlying_target=target,
        )
        if trade is not None:
            created.append(trade)
    return created


def execute_option_open(
    book: OptionBook,
    *,
    on: Date,
    underlying_provider: UnderlyingDateProvider,
    chain_provider: ChainProvider | None = None,
    notify_events: bool = False,
) -> list[OptionTrade]:
    """Fill PENDING long calls at the next open's underlying + hybrid premium."""
    chain_provider = chain_provider or _default_chain_provider
    opened: list[OptionTrade] = []
    for t in book.pending_trades():
        under = underlying_provider(t.ticker, on)
        if under is None:
            continue
        contract = OptionContract(
            option_type=t.option_type, strike=t.strike, expiry=t.expiry or on,
            dte=t.dte_at_entry, iv=t.entry_iv, delta=t.entry_delta, source=t.price_source,
        )
        chain = chain_provider(t.ticker, settings.option_target_dte, on)
        prem, source = entry_premium(
            contract, underlying=under, on=on, chain=chain, risk_free_rate=settings.risk_free_rate,
        )
        bps = 0.0 if source == "chain" else settings.option_slippage_bps_model
        fill = prem * (1.0 + bps / 10_000.0)
        t.price_source = source
        done = book.execute_pending(t, fill_premium=fill, on=on, underlying=under)
        opened.append(done)
    if notify_events:
        for t in opened:
            notify.notify_option_opened(t)
    return opened


def monitor_option_positions(
    book: OptionBook,
    *,
    on: Date,
    underlying_provider: UnderlyingProvider,
    notify_events: bool = False,
) -> list[OptionTrade]:
    """Mark OPEN calls (Black-Scholes) and close the first that trips an exit rule."""
    closed: list[OptionTrade] = []
    for t in book.open_trades():
        under = underlying_provider(t.ticker)
        if under is None:
            continue
        prem = mark_premium(
            t, underlying=under, on=on, iv=t.entry_iv, risk_free_rate=settings.risk_free_rate,
        )
        reason = evaluate_exit(t, underlying=under, premium=prem, on=on)
        if reason:
            exit_prem = max(0.0, under - t.strike) if reason == "EXIT_EXPIRY" else prem
            done = book.close_trade(
                t, exit_premium=exit_prem, exit_reason=reason, on=on, underlying=under,
            )
            closed.append(done)
    if notify_events:
        for t in closed:
            notify.notify_option_closed(t)
    return closed
```

Note on `planned_dollars`: each name is funded at `max_position_pct * budget`; `create_pending` floors that to whole contracts and returns `None` if not even one fits.

- [ ] **Step 5: Add notification formats to `src/agent/notify.py`**

Add `OptionTrade` to the storage import line in `notify.py`:

```python
from src.core.storage import PaperTrade, OptionTrade
```

Append after `notify_daily_summary`:

```python
_OPT_EXIT_ICON = {
    "EXIT_STOP": "🛑 STOP",
    "EXIT_TARGET": "🎯 TARGET",
    "EXIT_OPT_TP": "🎯 +PREM",
    "EXIT_OPT_SL": "🛑 -PREM",
    "EXIT_DTE": "⏲ DTE",
    "EXIT_EXPIRY": "📅 EXPIRY",
}


def format_option_opened(t: OptionTrade) -> str:
    exp = t.expiry.isoformat() if t.expiry else "?"
    return (
        f"📈 OPENED {t.ticker} {t.strike:g}C {exp}: {t.contracts}x @ ${t.entry_premium:,.2f} "
        f"(${t.cost_basis:,.0f}, {t.price_source})"
    )


def format_option_closed(t: OptionTrade) -> str:
    icon = _OPT_EXIT_ICON.get(t.exit_reason, t.exit_reason or "CLOSED")
    sign = "+" if t.pnl_dollars >= 0 else ""
    return (
        f"{icon} {t.ticker} {t.strike:g}C: {sign}${t.pnl_dollars:,.0f} "
        f"({sign}{t.pnl_pct:.1f}%) in {t.holding_days}d"
    )


def notify_option_opened(t: OptionTrade) -> str:
    line = format_option_opened(t)
    logger.info(line)
    _desktop_best_effort(f"📈 {t.ticker} call opened", line)
    return line


def notify_option_closed(t: OptionTrade) -> str:
    line = format_option_closed(t)
    logger.info(line)
    _desktop_best_effort(f"{t.ticker} call closed", line)
    return line
```

- [ ] **Step 6: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_option_jobs.py -q`
Expected: PASS (4 passed).

- [ ] **Step 7: Run full suite + mypy**

Run: `./.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: all pass.
Run: `./.venv/Scripts/python.exe -m mypy --strict src`
Expected: Success. (If `entry_premium`'s `Any` contract param triggers an attribute warning, it won't under `Any`; if `OptionContract` unused-import warns, keep the `# noqa: F401`/remove it.)

- [ ] **Step 8: Commit**

```bash
git add src/agent/jobs.py src/agent/notify.py tests/test_option_jobs.py
git commit -m "feat(options): queue/fill/monitor jobs + option notifications"
```

---

## Task 11: Daily summary + cashbook snapshot for the option book

**Files:**
- Modify: `src/agent/jobs.py` (add `option_daily_summary`)
- Test: `tests/test_option_jobs.py` (add a case)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_option_jobs.py`:

```python
def test_option_daily_summary_writes_cashbook() -> None:
    store = Storage.in_memory()
    book = OptionBook(store, budget=5000.0)
    from src.core.options.contracts import OptionContract
    c = OptionContract(option_type="call", strike=95.0, expiry=date(2024, 4, 19),
                       dte=45, iv=0.30, delta=0.60, source="model")
    t = book.create_pending(ticker="NVDA", strategy="composite", contract=c, snapshot={},
                            planned_dollars=1500.0, entry_premium_est=7.0,
                            underlying_stop=90.0, underlying_target=120.0)
    book.execute_pending(t, fill_premium=7.0, on=date(2024, 3, 1), underlying=100.0)
    jobs.option_daily_summary(
        store, on=date(2024, 3, 4),
        underlying_provider=lambda t: 102.0,
        voo_price=None,
    )
    cb = store.get_option_cashbook()
    assert len(cb) == 1
    assert cb[0].total_nav > 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_option_jobs.py -k daily_summary -q`
Expected: FAIL with `AttributeError: ... has no attribute 'option_daily_summary'`.

- [ ] **Step 3: Write the implementation**

Append to the options section of `src/agent/jobs.py`:

```python
def option_daily_summary(
    store: Storage,
    *,
    on: Date,
    underlying_provider: UnderlyingProvider,
    voo_price: float | None,
) -> str:
    """Mark the option book to NAV, write an option_cashbook row, notify once."""
    book = OptionBook(store)
    marks: dict[int, float] = {}
    for t in book.open_trades():
        under = underlying_provider(t.ticker)
        if under is None:
            continue
        marks[t.trade_id or -1] = mark_premium(
            t, underlying=under, on=on, iv=t.entry_iv, risk_free_rate=settings.risk_free_rate,
        )
    nav = book.current_nav(marks)
    invested = book.invested_value(marks)
    history = store.get_option_cashbook()
    voo_start = next((c.voo_price for c in history if c.voo_price), voo_price)
    voo_nav = book.voo_nav(voo_start, voo_price) if (voo_price and voo_start) else book.budget
    regime = store.latest_regime().label if store.latest_regime() else ""
    store.upsert_option_cashbook(
        date=on, total_nav=nav, voo_nav=voo_nav, invested_value=invested,
        regime=regime, voo_price=voo_price or 0.0,
    )
    closed_today = [t for t in book.closed_trades() if t.exit_date == on]
    realized = sum(t.pnl_dollars for t in closed_today)
    return notify.notify_daily_summary(
        nav=nav, budget=book.budget, open_count=len(book.open_trades()),
        closed_today=len(closed_today), realized_today=realized,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_option_jobs.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add src/agent/jobs.py tests/test_option_jobs.py
git commit -m "feat(options): daily NAV summary + cashbook snapshot"
```

---

## Task 12: Scheduler wiring — branch the paper jobs on trade_instrument

**Files:**
- Modify: `src/agent/jobs.py` (add scheduler-entry wrappers `run_option_market_open`, `run_option_monitor`, `run_option_summary`; extend `daily_eval` to also queue options)
- Modify: `src/agent/scheduler.py` (register the option jobs when `trade_instrument` includes options)
- Test: `tests/test_option_jobs.py` (add a wiring test)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_option_jobs.py`:

```python
def test_daily_eval_queues_options_when_enabled(monkeypatch: "pytest.MonkeyPatch") -> None:
    from src.core.config import settings as cfg
    store = Storage.in_memory()
    on = date(2024, 3, 1)
    _seed_candidate(store, "NVDA", on=on, score=80, rank=1, grade="HIGH-QUALITY")
    store.upsert_prices("NVDA", _price_df(100.0))

    monkeypatch.setattr(cfg, "trade_instrument", "option")
    monkeypatch.setattr(cfg, "enable_paper_trading", True)
    # avoid the network signal cycle: drive the option queue directly
    book = OptionBook(store, budget=cfg.paper_budget)
    jobs.queue_option_entries(
        book, store, on=on, regime_label="RISK_ON",
        price_provider=lambda t: store.get_prices(t),
        chain_provider=lambda t, dte, as_of: None,
    )
    assert len(store.get_option_trades(status="PENDING")) == 1
```

(This test asserts the queue path works under `trade_instrument="option"`; the full
`daily_eval` network cycle is covered by existing resilience tests.)

- [ ] **Step 2: Run test to verify it fails (or passes trivially)**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_option_jobs.py -k daily_eval_queues -q`
Expected: PASS already (it exercises existing functions). If it errors on import of a not-yet-added symbol, proceed to Step 3 first.

- [ ] **Step 3: Extend `daily_eval` and add scheduler wrappers**

In `src/agent/jobs.py`, modify `daily_eval` so its paper block also queues options. Replace the existing paper block inside `daily_eval`:

```python
    if settings.enable_paper_trading and result.bar_date is not None:
        if settings.trade_instrument in ("stock", "both"):
            book = PaperBook(store)
            queue_daily_exits(book, store, on=result.bar_date, regime_label=result.regime_label)
            queue_entries(book, store, on=result.bar_date, regime_label=result.regime_label)
        if settings.enable_options and settings.trade_instrument in ("option", "both"):
            obook = OptionBook(store)
            queue_option_entries(
                obook, store, on=result.bar_date, regime_label=result.regime_label,
                price_provider=store.get_prices,
            )
```

Add scheduler-entry wrappers in the calendar/scheduler section of `jobs.py` (after `run_daily_summary`):

```python
def _option_underlying_now(ticker: str) -> float | None:
    return execution.get_current_price(ticker)


def run_option_market_open(store: Storage | None = None) -> None:
    """Scheduler entry (~9:31): fill PENDING option entries at the open."""
    on = _today_market()
    if not (settings.enable_options and settings.trade_instrument in ("option", "both")
            and is_trading_day(on)):
        return
    store = store or Storage()
    book = OptionBook(store)
    if not book.pending_trades():
        return
    execute_option_open(
        book, on=on,
        underlying_provider=lambda t, d: execution.get_open_price(t, d),
        notify_events=True,
    )


def run_option_monitor(store: Storage | None = None) -> None:
    """Scheduler entry (every ~5 min): mark + exit OPEN option positions."""
    on = _today_market()
    if not (settings.enable_options and settings.trade_instrument in ("option", "both")
            and is_trading_day(on)):
        return
    store = store or Storage()
    book = OptionBook(store)
    if not book.open_trades():
        return
    monitor_option_positions(book, on=on, underlying_provider=_option_underlying_now, notify_events=True)


def run_option_summary(store: Storage | None = None) -> None:
    """Scheduler entry (~16:30): option NAV summary + cashbook row."""
    on = _today_market()
    if not (settings.enable_options and settings.trade_instrument in ("option", "both")
            and is_trading_day(on)):
        return
    store = store or Storage()
    voo = execution.get_current_price(settings.portfolio_benchmark)
    option_daily_summary(store, on=on, underlying_provider=_option_underlying_now, voo_price=voo)
```

- [ ] **Step 4: Register the jobs in `src/agent/scheduler.py`**

Inside `run_scheduled`, after the existing `if settings.enable_paper_trading:` block that
registers the three stock jobs, add a parallel registration (reusing the same time vars):

```python
    if settings.enable_options and settings.trade_instrument in ("option", "both"):
        o_open_h, o_open_m = settings.market_open_hm
        o_start_h, _ = settings.monitor_start_hm
        o_end_h, _ = settings.monitor_end_hm
        o_sum_h, o_sum_m = settings.daily_summary_hm
        scheduler.add_job(
            jobs.run_option_market_open,
            trigger=CronTrigger(day_of_week="mon-fri", hour=o_open_h, minute=o_open_m,
                                timezone=settings.market_tz),
            id="option_market_open", name="Market-open option fills",
            misfire_grace_time=600, coalesce=True,
        )
        scheduler.add_job(
            jobs.run_option_monitor,
            trigger=CronTrigger(day_of_week="mon-fri", hour=f"{o_start_h}-{o_end_h}",
                                minute=f"*/{settings.monitor_interval_minutes}",
                                timezone=settings.market_tz),
            id="option_monitor", name="Intraday option monitor",
            misfire_grace_time=settings.monitor_interval_minutes * 60, coalesce=True,
        )
        scheduler.add_job(
            jobs.run_option_summary,
            trigger=CronTrigger(day_of_week="mon-fri", hour=o_sum_h, minute=o_sum_m,
                                timezone=settings.market_tz),
            id="option_summary", name="End-of-day option summary",
            misfire_grace_time=3600, coalesce=True,
        )
```

- [ ] **Step 5: Run tests + mypy**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_option_jobs.py -q`
Expected: PASS.
Run: `./.venv/Scripts/python.exe -m mypy --strict src`
Expected: Success.

- [ ] **Step 6: Commit**

```bash
git add src/agent/jobs.py src/agent/scheduler.py tests/test_option_jobs.py
git commit -m "feat(options): scheduler wiring + daily_eval branches on trade_instrument"
```

---

## Task 13: Options dashboard page

**Files:**
- Create: `src/dashboard/pages/options.py`
- Modify: `src/dashboard/app.py` (register the page)
- Modify: `tests/test_dashboard.py` (add `options` to the smoke list + helper tests)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_dashboard.py` (and add `options` to `PAGE_MODULES`):

Change the `PAGE_MODULES` line to:

```python
PAGE_MODULES = ["overview", "chart", "value_chain", "portfolio", "trades", "options", "backtest", "alerts"]
```

Append these helper tests:

```python
def test_options_win_rate_breakdown() -> None:
    from src.dashboard.pages import options
    from src.core.storage import OptionTrade

    closed = [
        OptionTrade(ticker="A", status="CLOSED", exit_reason="EXIT_TARGET", pnl_dollars=300.0),
        OptionTrade(ticker="B", status="CLOSED", exit_reason="EXIT_OPT_SL", pnl_dollars=-150.0),
    ]
    bd = options.win_rate_breakdown(closed)
    assert bd["EXIT_TARGET"]["win_rate"] == 100.0
    assert bd["EXIT_OPT_SL"]["win_rate"] == 0.0


def test_options_equity_curve_indexes_to_100() -> None:
    from datetime import date
    from src.dashboard.pages import options
    from src.core.storage import OptionCashbook

    cb = [
        OptionCashbook(date=date(2024, 1, 2), total_nav=5000.0, voo_nav=5000.0),
        OptionCashbook(date=date(2024, 1, 3), total_nav=5500.0, voo_nav=5100.0),
    ]
    df = options.equity_curve_df(cb)
    assert df["Option NAV"].iloc[1] == pytest.approx(110.0)
    assert df["VOO"].iloc[1] == pytest.approx(102.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_dashboard.py -k options -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.dashboard.pages.options'`.

- [ ] **Step 3: Write the page**

Create `src/dashboard/pages/options.py`:

```python
"""Options page (Session 16): the autonomous option engine's book + journal.

Simulated long-call account. Entry premiums may use a live chain when available;
every mark and the backtest use Black-Scholes. Model-priced (illiquid) names are
flagged — their results are NOT realistic. Never connected to a broker.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Sequence

import pandas as pd
import streamlit as st

from src.core.config import settings
from src.core.storage import OptionCashbook, OptionTrade, Storage
from src.dashboard.components.data import get_store

_DISCLAIMER = (
    "⚠️ **Options paper trading — simulated money only.** Entry may use a live chain; "
    "all marks + the backtest use Black-Scholes (no IV smile/skew, no earnings IV crush). "
    "Names tagged `model` have **no real options market** behind them — their results are "
    "not realistic. Estimated slippage, ~15-min delayed data, no broker."
)
_MIN_TRADES_FOR_STATS = 10


def win_rate_breakdown(closed: Sequence[OptionTrade]) -> dict[str, dict[str, Any]]:
    """Group closed option trades by exit reason → {reason: {n, wins, win_rate, avg_pnl}}."""
    buckets: dict[str, list[OptionTrade]] = defaultdict(list)
    for t in closed:
        buckets[t.exit_reason or "—"].append(t)
    out: dict[str, dict[str, Any]] = {}
    for reason, trades in buckets.items():
        wins = sum(1 for t in trades if t.pnl_dollars > 0)
        out[reason] = {
            "n": len(trades),
            "wins": wins,
            "win_rate": (wins / len(trades) * 100.0) if trades else 0.0,
            "avg_pnl": sum(t.pnl_dollars for t in trades) / len(trades) if trades else 0.0,
        }
    return out


def equity_curve_df(cashbook: Sequence[OptionCashbook]) -> pd.DataFrame:
    """Option NAV vs same-dollar VOO, indexed to 100 at the first snapshot."""
    if not cashbook:
        return pd.DataFrame()
    base_nav = cashbook[0].total_nav or 1.0
    base_voo = next((c.voo_nav for c in cashbook if c.voo_nav), None)
    rows = []
    for c in cashbook:
        row: dict[str, Any] = {"date": c.date, "Option NAV": (c.total_nav / base_nav) * 100}
        if base_voo and c.voo_nav:
            row["VOO"] = (c.voo_nav / base_voo) * 100
        rows.append(row)
    return pd.DataFrame(rows).set_index("date")


def render(storage: Storage | None = None) -> None:
    storage = storage or get_store()
    st.header("📐 Autonomous Option Trades")
    st.warning(_DISCLAIMER)

    open_trades = storage.get_option_trades(status="OPEN")
    pending = storage.get_option_trades(status="PENDING")
    closed = storage.get_option_trades(status="CLOSED")
    cashbook = storage.get_option_cashbook()

    if not (open_trades or pending or closed or cashbook):
        st.info(
            "No option trades yet. Set `trade_instrument` to `option` or `both` and run "
            "the agent — it queues calls at the daily close and fills them at the next open."
        )
        return

    budget = settings.paper_budget
    latest_nav = cashbook[-1].total_nav if cashbook else budget
    pnl = latest_nav - budget
    voo_nav = cashbook[-1].voo_nav if cashbook else budget
    alpha = latest_nav - voo_nav

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Option NAV", f"${latest_nav:,.0f}", f"{pnl / budget * 100:+.1f}%")
    c2.metric("Budget", f"${budget:,.0f}")
    c3.metric("VOO (same $)", f"${voo_nav:,.0f}")
    c4.metric("Alpha vs VOO", f"${alpha:,.0f}", f"{alpha / budget * 100:+.1f}%")

    curve = equity_curve_df(cashbook)
    if not curve.empty:
        st.subheader("Equity curve — option NAV vs VOO (indexed to 100)")
        st.line_chart(curve)

    st.subheader(f"Open positions ({len(open_trades)})")
    if open_trades:
        st.dataframe(
            pd.DataFrame(
                [{"Ticker": t.ticker, "Call": f"{t.strike:g}",
                  "Expiry": t.expiry.isoformat() if t.expiry else "—",
                  "Contracts": t.contracts, "Entry $": f"${t.entry_premium:,.2f}",
                  "Cost": f"${t.cost_basis:,.0f}", "Src": t.price_source,
                  "U-stop": f"${t.underlying_stop:,.2f}", "U-target": f"${t.underlying_target:,.2f}",
                  "Queued exit": t.pending_exit_reason or "—"}
                 for t in open_trades]
            ),
            use_container_width=True, hide_index=True,
        )
    else:
        st.caption("No open positions.")

    if pending:
        st.subheader(f"Pending entries ({len(pending)}) — fill at next open")
        st.dataframe(
            pd.DataFrame(
                [{"Ticker": t.ticker, "Call": f"{t.strike:g}", "Contracts": t.contracts,
                  "Src": t.price_source} for t in pending]
            ),
            use_container_width=True, hide_index=True,
        )

    st.subheader(f"Closed trades ({len(closed)})")
    if closed:
        st.dataframe(
            pd.DataFrame(
                [{"Ticker": t.ticker, "Call": f"{t.strike:g}", "Exit": t.exit_reason,
                  "P&L $": round(t.pnl_dollars, 0), "P&L %": round(t.pnl_pct, 1),
                  "Days": t.holding_days, "Src": t.price_source}
                 for t in reversed(closed)]
            ),
            use_container_width=True, hide_index=True,
        )
        with st.expander("Trade decision snapshots (why the agent acted)"):
            for t in reversed(closed[-20:]):
                snap = json.loads(t.signal_snapshot_json or "{}")
                st.markdown(
                    f"**{t.ticker}** {t.strike:g}C · {t.exit_reason} · {t.pnl_pct:+.1f}% · "
                    f"composite {snap.get('composite', '—')} · grade {snap.get('grade', '—')}"
                )

    st.subheader("Win-rate breakdown")
    if len(closed) < _MIN_TRADES_FOR_STATS:
        st.caption(f"Collecting data — need {_MIN_TRADES_FOR_STATS}+ closed trades (have {len(closed)}).")
    else:
        breakdown = win_rate_breakdown(closed)
        st.dataframe(
            pd.DataFrame(
                [{"Exit reason": k, "Trades": v["n"], "Win rate": f"{v['win_rate']:.0f}%",
                  "Avg P&L $": round(v["avg_pnl"], 0)}
                 for k, v in sorted(breakdown.items(), key=lambda kv: -kv[1]["n"])]
            ),
            use_container_width=True, hide_index=True,
        )
```

- [ ] **Step 4: Register the page in `src/dashboard/app.py`**

Add `options` to the page import block:

```python
from src.dashboard.pages import (
    alerts,
    backtest,
    chart,
    options,
    overview,
    portfolio,
    trades,
    value_chain,
)
```

Add the page line after the Paper Trades line in `main`:

```python
            st.Page(options.render, title="Option Trades", icon="📐", url_path="options"),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_dashboard.py -q`
Expected: PASS (all dashboard tests, including the two new option helpers + the `options` smoke render).

- [ ] **Step 6: Commit**

```bash
git add src/dashboard/pages/options.py src/dashboard/app.py tests/test_dashboard.py
git commit -m "feat(options): Option Trades dashboard page"
```

---

## Task 14: Full green + docs + memory

**Files:**
- Modify: `CLAUDE.md` (note Session 16)
- Test: full suite + mypy

- [ ] **Step 1: Run the full suite**

Run: `./.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: all pass (Session 15 count + the new option tests).

- [ ] **Step 2: Run mypy strict (fresh cache)**

Run: `rm -rf .mypy_cache && ./.venv/Scripts/python.exe -m mypy --strict --no-incremental src`
Expected: `Success: no issues found`.

- [ ] **Step 3: Note Session 16 in `CLAUDE.md`**

Append a short paragraph to the Status block in `CLAUDE.md` noting the options layer:
"Session 16 (options expression layer) adds `src/core/options/` (Black-Scholes pricing/greeks, realized-vol IV, live-chain fetch, contract selection by target delta/DTE, `OptionBook` long-call paper engine), `option_trades`+`option_cashbook` tables, option queue/fill/monitor/summary jobs branched on `trade_instrument`, and an **Option Trades** dashboard page. Hybrid pricing: live chain at entry, Black-Scholes for all marks + backtest. Long calls only; spreads/puts/backtest-options deferred."

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: note Session 16 options layer in CLAUDE.md"
```

---

## Deferred (not in this plan)

- Options mode for the Session 14 walk-forward backtest (BS-priced calls replayed) —
  the spec lists it; defer to a follow-up plan to keep this one focused on live paper.
- Multi-leg structures (debit spreads), puts/bearish expressions, IV smile/skew/term
  structure, early-exercise/assignment, the Claude-API trade-autopsy learning loop.

---

## Self-Review notes

- **Spec coverage:** pricing (T2), vol (T3), chain (T5), contracts (T4), option book +
  greeks-aware sizing (T7), marking + 6 exits + expiry (T8), hybrid entry premium (T9),
  storage tables (T6), jobs + notify (T10–11), scheduler + `trade_instrument` (T12),
  dashboard (T13), config (T1), docs (T14). The **options backtest** is explicitly
  deferred (noted above) — flagged so it isn't silently dropped.
- **Coexistence:** stock book untouched; option book gated by `trade_instrument` + `enable_options`.
- **Type consistency:** `OptionContract` fields, `OptionTrade` columns, and the
  `entry_premium`/`mark_premium`/`evaluate_exit` signatures are used identically across
  tasks. Exit-reason strings (`EXIT_STOP/TARGET/OPT_TP/OPT_SL/DTE/EXPIRY`) match between
  T8 and the T13 icon map.
- **Trade-all universe:** no liquidity gate on entry (per decision); illiquid names get a
  `model` price source and the dashboard flags them.
