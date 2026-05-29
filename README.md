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

# Background agent (daily-close scheduler)            [available from Session 4]
python -m src.agent

# Dashboard at http://localhost:8501                  [available from Session 5]
streamlit run src/dashboard/app.py
```

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
- [ ] Session 4 — signal orchestrator + background agent
- [ ] Session 5 — dashboard
- [ ] Session 6 — testing, edge cases, polish
