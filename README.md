# AI Value Chain Trading Agent

A background agent + Streamlit dashboard that monitors AI data-center infrastructure
stocks across the full value chain, evaluating four entry strategies (EMA pullback,
consolidation breakout, ATH pullback, IPO base) to surface higher-probability setups.

See [CLAUDE.md](CLAUDE.md) for the full spec, thesis, and per-session build plan.

## Resolved architecture (v1)

- **Runs on:** this laptop (Windows). Daily-close evaluation; no always-on server needed.
- **Data:** `yfinance` only (no API key). A fallback source can be added behind `data.fetch_prices` later.
- **Cadence:** one evaluation after US market close on trading weekdays.
- **Dashboard:** localhost only, no auth.
- **TA:** `pandas-ta` 0.4.71b0 + TA-Lib 0.6.x for candlestick patterns (requires NumPy ≥2.2.6).

## Requirements

- Python 3.12 (`pandas-ta` 0.4.x requires ≥3.12)
- [`uv`](https://github.com/astral-sh/uv) (recommended) or pip
- **TA-Lib** — installed automatically via the `TA-Lib>=0.6` wheel (no manual C build needed on Windows/macOS/Linux for supported Python versions).

## Setup

```powershell
uv sync                          # or: pip install -e ".[dev]"
Copy-Item .env.example .env      # optional — edit thresholds/paths
```

## Usage

```powershell
# One-shot evaluation cycle (testing / manual run)  [available from Session 4]
python -m src.agent --once

# Check the watchlist loads and every ticker is fetchable  [Session 6]
python -m src.agent --validate

# Background agent (daily-close scheduler)            [available from Session 4]
python -m src.agent

# Dashboard at http://localhost:8501                  [available from Session 5]
streamlit run src/dashboard/app.py
```

With [`just`](https://github.com/casey/just) installed, the `justfile` wraps these
against the project venv: `just test`, `just types`, `just validate`,
`just fetch-once`, `just run-agent`, `just run-dashboard`.

## Project layout

```
src/core/      config, watchlist, data, indicators, patterns, strategies/, signals, storage
src/agent/     scheduler, jobs, notify        (Session 4)
src/dashboard/ Streamlit app + pages           (Session 5)
tests/         pytest suite
data/          tracker.db (SQLite, gitignored)
```

## Configuration

All thresholds and paths are typed config in [src/core/config.py](src/core/config.py),
overridable via environment variables (prefix `AITT_`) or a `.env` file. See
[.env.example](.env.example) for every available key. Nothing is hardcoded.

## Watchlist

Edit [src/core/watchlist.yaml](src/core/watchlist.yaml) — `{ticker, name, layer, notes}`
per entry. The agent hot-reloads it on the next cycle.

## Development

```powershell
uv run pytest -q          # run the test suite
uv run mypy src           # strict type check
```

## Build status

- [x] **Session 1** — scaffolding + data layer (config, watchlist, data, storage)
- [x] **Session 2** — EMA pullback + ATH pullback + bullish patterns + confidence scoring
- [x] **Session 3** — consolidation breakout + IPO base
- [x] **Session 4** — signal orchestrator + background agent (daily-close scheduler, notifications, `--once` CLI)
- [x] **Session 5** — Streamlit dashboard (overview, chart, value chain, alerts)
- [x] **Session 6** — hardening: rotating file log, `--validate` watchlist check, resilience + pipeline tests, `justfile`
- [x] **Session 7** — setup quality scorecard (trend / volume / earnings / rel-strength / R:R / resistance / leading layer / breadth) + composite grade
- [x] **Session 8** — evidence layer: historical win-rate replay + catalysts (earnings beat/miss + headlines)
- [x] **Session 9** — trade due diligence dossier: bull vs bear case ("why NOT buy?") + trade plan (stop/invalidation/targets/sizing) + EMA-200 alignment + informational market regime
- [x] **Session 10** — market-regime gate (indices vs 50 EMA → RISK_ON/NEUTRAL/RISK_OFF) + automatic disqualifiers (suppress/downgrade bad alerts at the source)
- [x] **Session 11** — 0-100 composite score + cross-sectional ranking + allocation + layer rotation + AI-thesis tracker
- [x] **Session 12** — deeper signals: accumulation (OBV/A-D), weekly trend alignment, Weinstein stage, ATR crowding, AI-capex exposure
- [x] **Session 13** — portfolio exposure management (paper): regime exposure dial + 3-day hysteresis, conviction sizing + concentration caps, RS rotation, Portfolio dashboard page (NAV vs VOO)
- [ ] Session 14 — walk-forward backtest vs VOO (the verdict)
- [ ] v2 (deferred) — portfolio-aware: holdings input → exits, concentration, opportunity-cost-vs-holdings, Bayesian probability
