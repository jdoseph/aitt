# AI Value Chain Trading Agent

A background agent + dashboard that monitors AI infrastructure stocks across the full data center value chain, using multiple entry strategies to find higher-probability setups — not just EMA pullbacks.

## Why this exists

**The thesis:** Before OpenAI and Anthropic IPO (expected 2026), money flows into publicly traded AI infrastructure as proxy plays. After the IPOs, the entire AI value chain reprices. The goal is to be positioned in the right names *before* these catalysts hit — but without chasing parabolic moves.

**The problem with EMA-only:** Many AI stocks are at all-time highs, far above their 9/21 EMAs. Waiting for an EMA touch on NVDA, VRT, or AVGO could mean waiting months — essentially waiting for a market crash. EMA pullback works for stocks that are trending but not parabolic. For extended names, we need different strategies.

**The solution:** Four complementary entry strategies that cover both pullback and breakout scenarios, plus an IPO-specific strategy for when Anthropic/OpenAI actually list. The agent evaluates all strategies in parallel and surfaces the best setups daily.

### Reference material

The watchlist and value chain understanding is informed by:
- **Silicon Analysts** — "AI Data Center Value Chain" (2026): 52 companies, 86 supply chain relationships across 10 layers. Identifies interconnects as the emerging bottleneck.
- **Spear Invest** — "AI Data Center Deep Dive": Data center TAM breakdown. Inside the rack (processors 61%, networking 15%, HBM 5%). Outside the rack (power 20% CAGR, thermal 40% CAGR). Top 3 players (Vertiv, Schneider, Eaton) control 45% of outside-the-rack market.
- **Yallo Group** — "The New AI Value Chain": Layers from data infrastructure → compute → models → applications → governance. Global AI market projected $371B (2025) to $2.4T (2032).
- **NVIDIA 800 VDC Architecture** — 800V DC power distribution for next-gen AI data centers. Partners: ABB, Eaton, Schneider, Siemens, Vertiv, GE Vernova, Delta, TI, Infineon, Analog Devices, onsemi, Renesas.

---

## Working with this spec

**This project is built across 14 sequential sessions** defined in the "Implementation sessions" section. Each session is scoped and self-contained. At the start of each session:

1. **Re-read this CLAUDE.md** — it may have been updated since the last session
2. **Check the Open questions section** — resolve any 🔴 items before writing code if not yet answered
3. **Do not skip ahead** — complete the current session's verification checklist before starting the next
4. **If you hit a decision not covered here**, stop and ask the user rather than guess

**When a decision is made**, update this file. CLAUDE.md is the source of truth — keep it accurate so the next session has correct context.

---

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.11+ | Best ecosystem for finance/TA |
| Market data | `yfinance` | Free, no API key, sufficient for daily EMA |
| Indicators | `pandas` + `pandas-ta` | Standard TA library, vectorized |
| Dashboard | `streamlit` | Fastest way to build a live dashboard |
| Scheduler | `APScheduler` | Background jobs in-process |
| Storage | `SQLite` | Zero-config, sufficient for state/history |
| Notifications | `plyer` (desktop) + console | Local-first; webhook/email added later |
| Config | `pydantic-settings` + `.env` | Type-safe config |
| Testing | `pytest` | Standard |

**Open decision — alerts:** defaulting to desktop notifications + dashboard. If you want email or Discord/Slack webhooks, say so and I'll wire them in.

> **Note on TA library (verified 2026-05-29):** Keeping `pandas-ta` per the table. The current PyPI release is the maintained rewrite **`pandas-ta` 0.4.71b0**, which requires **Python ≥3.12** and **NumPy ≥2.2.6** (the old `numpy.NaN` import bug is gone). Its candlestick functions wrap **TA-Lib**, installed via the prebuilt **`TA-Lib` 0.6.x** wheel (works on Windows cp312 — no manual C build). Installed stack confirmed importing: numpy 2.2.6, talib 0.6.8, pandas_ta 0.4.71b0. Pins are encoded in `pyproject.toml`. Note: project lives under OneDrive, so uv uses `link-mode = "copy"` (hardlinks fail there).

---

## Architecture

```
ai-infra-tracker/
├── CLAUDE.md
├── README.md
├── pyproject.toml
├── .env.example
├── data/
│   └── tracker.db              # SQLite: prices, signals, alert history
├── src/
│   ├── core/
│   │   ├── config.py           # Pydantic settings, watchlist loading
│   │   ├── watchlist.py        # Watchlist categories + tickers + value chain layers
│   │   ├── data.py             # yfinance fetch, caching, retries
│   │   ├── indicators.py       # EMA calc, ATH calc, volume averages
│   │   ├── patterns.py         # Bullish candlestick pattern detection + confidence scoring
│   │   ├── strategies/
│   │   │   ├── base.py         # Abstract strategy interface
│   │   │   ├── ema_pullback.py # Strategy 1: 9/21 EMA pullback
│   │   │   ├── consolidation_breakout.py  # Strategy 2: flag/base breakout
│   │   │   ├── ath_pullback.py # Strategy 3: % pullback from ATH
│   │   │   └── ipo_base.py     # Strategy 4: IPO base breakout
│   │   ├── signals.py          # Orchestrator: runs all strategies, deduplicates
│   │   ├── levels.py           # Resistance, suggested stop, risk/reward (Session 7)
│   │   ├── benchmarks.py       # SPY/QQQ/SMH relative strength (Session 7)
│   │   ├── earnings.py         # Next earnings date / days-to-earnings (Session 7)
│   │   ├── market.py           # AI breadth + value-chain layer leadership (Session 7)
│   │   ├── scorecard.py        # 8-check setup quality grade (Session 7; +9/10 in Session 8)
│   │   ├── backtest.py         # Historical signal win-rate replay (Session 8)
│   │   ├── news.py             # Recent catalysts via yfinance headlines (Session 8)
│   │   ├── dossier.py          # Bull/bear case + trade plan (Session 9)
│   │   ├── regime.py           # Market regime RISK_ON/OFF from indices vs 50 EMA (Session 10)
│   │   ├── gating.py           # Automatic disqualifiers / alert suppression (Session 10)
│   │   ├── scoring.py          # 0-100 composite setup score (Session 11)
│   │   ├── ranking.py          # Cross-sectional RS rank, opportunity order, allocation (Session 11)
│   │   ├── accumulation.py     # OBV / A-D / up-down volume (Session 12)
│   │   ├── multitimeframe.py   # Weekly trend alignment (Session 12)
│   │   ├── stage.py            # Weinstein Stage 1-4 classification (Session 12)
│   │   ├── portfolio.py        # Paper portfolio state, target weights, rebalance suggestions (S13)
│   │   ├── exposure.py         # Regime → total-exposure dial + hysteresis (S13)
│   │   ├── sizing.py           # Conviction sizing + RS rotation + concentration caps (S13)
│   │   ├── backtest_portfolio.py  # Walk-forward portfolio backtest vs VOO (S14)
│   │   └── storage.py          # SQLite ORM (SQLModel)
│   ├── agent/
│   │   ├── scheduler.py        # APScheduler entry point
│   │   ├── jobs.py             # Refresh prices, evaluate signals, fire alerts
│   │   └── notify.py           # Desktop notifications, future webhook hooks
│   └── dashboard/
│       ├── app.py              # Streamlit entry point
│       ├── pages/
│       │   ├── overview.py     # Watchlist table with status per ticker, multi-strategy
│       │   ├── chart.py        # Per-ticker chart with EMAs, ATH, consolidation ranges
│       │   ├── value_chain.py  # Group by layer, show signal density per layer
│       │   └── alerts.py       # Alert history + acknowledged state, filterable
│       └── components/         # Reusable Streamlit pieces
└── tests/
    ├── test_indicators.py
    ├── test_patterns.py
    ├── test_ema_pullback.py
    ├── test_consolidation_breakout.py
    ├── test_ath_pullback.py
    ├── test_ipo_base.py
    ├── test_signals.py          # Integration: all strategies + confidence scoring
    └── test_storage.py
```

**Two processes, one DB:**
- `python -m src.agent` — runs in the background, evaluates signals once after US market close on trading weekdays (daily-close-only cadence; see resolved decisions)
- `streamlit run src/dashboard/app.py` — UI reads from the same SQLite DB

---

## Implementation sessions

Build this project across **14 sequential sessions**. Each session is self-contained — complete it fully, verify it works, then move to the next. Do not skip ahead. At the start of each session, **re-read this CLAUDE.md** and check if any open questions were resolved since last session.

> **Status:** **Sessions 1–12 are complete** (on `main`) — including Session 6 (hardening: rotating file-log sink, `python -m src.agent --validate`, `tests/test_resilience.py`, `justfile`). **Remaining: 13** (portfolio exposure management) and **14** (walk-forward backtest vs VOO) — the index-beating mechanism plus its validation; neither is built yet. **Session 12 was built before 11** (its deeper-signal outputs — accumulation, weekly trend, Weinstein stage, ATR/crowding, capex_exposure — are inputs the Session 11 composite score consumes). Sessions 11–12 build on the scorecard (7), evidence (8), dossier (9), and regime gate (10). A slimmed **v2 portfolio-aware track** (real-holdings exits, trade journal, Bayesian win-prob) is described after Session 14.
>
> **Note (Session 10 config):** the canonical RISK_ON/OFF gate uses `regime_gate_ema_span` (50). Session 9's *informational* 21-EMA line keeps `regime_ema_span` (21) — the two are intentionally separate knobs (the spec's "`regime_ema_span` (50)" for Session 10 was renamed to avoid clobbering Session 9's).
>
> **Theme of 10–12:** move the agent from a *chart scanner* ("is there a setup?") to a *decision-support tool* ("which AI-infra names deserve capital today, and which bad setups should never reach the dashboard?").

---

### Session 1 — Project scaffolding + data layer

**Goal:** Skeleton project that can fetch and store daily price data for the full watchlist.

**Build:**
- `pyproject.toml` with all dependencies (yfinance, pandas, pandas-ta, streamlit, apscheduler, sqlmodel, pydantic-settings, plyer, pytest)
- `.env.example` with placeholder config values
- `src/core/config.py` — Pydantic settings: thresholds, paths, feature flags
- `src/core/watchlist.yaml` — full watchlist from the Watchlist section below, schema: `{ticker, name, layer, notes}`
- `src/core/watchlist.py` — load + validate YAML, hot-reload support
- `src/core/data.py` — yfinance fetcher: pull last 200 daily candles for a ticker, batch fetch for full watchlist, retry logic, rate limiting
- `src/core/storage.py` — SQLite via SQLModel: tables for `prices` (ticker, date, OHLCV), `signals` (ticker, date, strategy, status, details), `alerts` (ticker, date, strategy, message, acknowledged)
- `README.md` — setup instructions

**Verify before moving on:**
- `python -c "from src.core.watchlist import load_watchlist; print(load_watchlist())"` — loads all ~40 tickers with layer tags
- `python -c "from src.core.data import fetch_prices; print(fetch_prices('NVDA').tail())"` — returns 5 rows of OHLCV
- Batch fetch all tickers, store in SQLite, confirm row counts
- All tests pass: `pytest tests/test_storage.py`

---

### Session 2 — Strategy 1 (EMA Pullback) + Strategy 3 (ATH Pullback) + Bullish Patterns

**Goal:** Two working strategies that can evaluate any ticker and return a signal classification, plus the bullish pattern detection module that scores signal confidence. These are grouped because they share the same data (daily OHLCV) and are pure math — no complex pattern detection.

**Build:**
- `src/core/indicators.py` — compute EMA_9, EMA_21, EMA_50, ATH (52-week), distance-to-EMA %, distance-to-ATH %, 20-day average volume
- `src/core/patterns.py` — bullish candlestick pattern detection using `pandas-ta`: bullish engulfing, hammer, morning star, three white soldiers, doji at support, piercing line. Each returns `{pattern_name, strength}`. Confidence scoring function: takes a strategy signal + detected patterns → returns star rating (1–3)
- `src/core/strategies/base.py` — abstract `Strategy` class: `evaluate(ticker_data) -> Signal` with fields `{ticker, strategy_name, status, details, confidence, patterns_detected, timestamp}`
- `src/core/strategies/ema_pullback.py` — Strategy 1 per the spec: EXTENDED, APPROACHING_9, AT_9_EMA, APPROACHING_21, AT_21_EMA, BELOW_21_EMA
- `src/core/strategies/ath_pullback.py` — Strategy 3 per the spec: AT_ATH, MINOR_PULLBACK, ENTRY_ZONE, DEEP_PULLBACK, CORRECTION. Include the "ATH within last 30 trading days" freshness check
- Tests: `test_indicators.py`, `test_patterns.py`, `test_ema_pullback.py`, `test_ath_pullback.py`

**Verify before moving on:**
- Run both strategies against NVDA, VRT, RDW, TXN — confirm classifications match what you'd see on a chart
- Pattern detection correctly identifies at least one bullish engulfing or hammer in recent history of any watchlist stock (scan all tickers, report which ones have recent patterns)
- Confidence scoring: manually verify that a signal with pattern confirmation scores higher than one without
- `python -m pytest tests/test_ema_pullback.py tests/test_ath_pullback.py tests/test_patterns.py -v` — all pass
- Edge cases: what happens with < 50 bars of data? Stock that just IPO'd? Ticker that yfinance can't find?

---

### Session 3 — Strategy 2 (Consolidation Breakout) + Strategy 4 (IPO Base)

**Goal:** Two pattern-detection strategies. These are more complex — they identify ranges, track consolidation duration, and detect breakouts on volume.

**Build:**
- `src/core/strategies/consolidation_breakout.py` — Strategy 2 per the spec: detect consolidation (price within X% range for N+ days), compute range boundaries, detect breakout/breakdown on volume. Statuses: CONSOLIDATING, BREAKOUT, BREAKDOWN, NO_PATTERN
- `src/core/strategies/ipo_base.py` — Strategy 4 per the spec: detect IPO (< 60 trading days), mark initial high, detect base, detect breakout. Statuses: IPO_FRESH, IPO_BASING, IPO_BREAKOUT, IPO_FAILED. This strategy should gracefully return NO_SIGNAL for non-IPO stocks
- Tests: `test_consolidation_breakout.py`, `test_ipo_base.py` — use synthetic price data to test pattern detection (e.g., flat candles then spike = breakout)

**Verify before moving on:**
- Consolidation strategy identifies at least one stock currently consolidating from the watchlist (or explain why none qualify)
- IPO strategy correctly returns NO_SIGNAL for all current watchlist stocks (none are recent IPOs)
- Test with synthetic data: 15 days of tight-range candles followed by a gap up on 2x volume → BREAKOUT
- `pytest tests/ -v` — all pass including sessions 1–2 tests

---

### Session 4 — Signal orchestrator + background agent

**Goal:** Wire all four strategies into an orchestrator that evaluates the full watchlist, deduplicates signals, stores results, and fires alerts. Add the APScheduler background agent.

**Build:**
- `src/core/signals.py` — orchestrator: for each ticker, run all 4 strategies, attach bullish pattern confidence scores to each signal, collect signals, deduplicate by `(ticker, strategy, status, date)`, write to SQLite, detect status transitions (previous vs. current), return list of new alerts to fire sorted by confidence (⭐⭐⭐ first)
- `src/agent/scheduler.py` — APScheduler entry point: **daily-close cadence (resolved)** — one evaluation cycle shortly after US market close (~4:15 PM ET) on trading weekdays. No 30-min intraday loop.
- `src/agent/jobs.py` — `refresh_prices()`: batch fetch all tickers; `evaluate_signals()`: run orchestrator; `fire_alerts()`: dispatch to notification layer
- `src/agent/notify.py` — desktop notifications via `plyer`, console logging. ⭐⭐⭐ alerts get higher priority (persistent notification vs. transient). Structured so email/webhook can be plugged in later without changing the interface
- CLI: `python -m src.agent` (background daemon) and `python -m src.agent --once` (single eval cycle for testing)

**Verify before moving on:**
- `python -m src.agent --once` runs successfully: fetches prices, evaluates all strategies for all tickers, prints signal summary to console, writes to SQLite
- Check `tracker.db` for populated `signals` table with all four strategy types
- Desktop notification fires for at least one test alert (manually lower a threshold if needed)
- Agent gracefully handles: yfinance timeout, missing ticker, weekend/after-hours (skips or waits)
- `pytest tests/test_signals.py -v` — orchestrator integration tests pass

---

### Session 5 — Dashboard

**Goal:** Streamlit dashboard with four pages: overview, chart, value chain, alerts.

**Build:**
- `src/dashboard/app.py` — Streamlit entry point with sidebar navigation
- `src/dashboard/pages/overview.py` — main table: ticker, price, % change, layer, active strategy signals (as colored badges), distance to 9/21 EMA, distance to ATH, consolidation status. Sortable by "closest to entry." Filterable by layer and strategy type
- `src/dashboard/pages/chart.py` — per-ticker candlestick chart (use `plotly` via streamlit): 9/21/50 EMA lines, ATH horizontal line, consolidation range shading, volume bars with 20-day avg line, signal markers. Ticker selector dropdown
- `src/dashboard/pages/value_chain.py` — group tickers by layer, show count of active signals per layer, expandable to see individual tickers. "Layer 4 — Interconnects: 2 approaching entry" style summary
- `src/dashboard/pages/alerts.py` — chronological alert log from SQLite, filterable by strategy + layer, ack/dismiss buttons
- `src/dashboard/components/` — reusable pieces: signal badge renderer, layer color mapping, chart builder

**Verify before moving on:**
- `streamlit run src/dashboard/app.py` — opens without errors
- Overview table loads all ~40 tickers with correct data from SQLite
- Chart renders for any selected ticker with all indicators visible
- Value chain view groups correctly by layer
- Alerts page shows historical alerts (run `--once` a few times first to populate)
- Dashboard reads from same `tracker.db` that the agent writes to

---

### Session 6 — Testing, edge cases, polish

**Goal:** Harden everything. Handle edge cases. Make it production-ready for daily use.

**Build:**
- Full test suite: unit tests for each strategy with edge cases, integration test for full pipeline (fetch → evaluate → store → alert)
- Edge case handling: ticker delisted or renamed, yfinance returns partial data, stock halted, stock splits (adjusted close), new ticker added to YAML mid-session
- Logging: structured logging throughout (use `loguru` or stdlib `logging`), log level configurable via .env
- Error recovery: agent continues if one ticker fails, logs the error, moves to next
- Config validation: startup check that all tickers in YAML are fetchable, warn on any that fail
- Documentation: update README with full setup, usage, screenshots, how to add tickers, how to adjust thresholds
- Optional: `Makefile` or `justfile` with commands: `make run-agent`, `make run-dashboard`, `make test`, `make fetch-once`

**Verify before moving on:**
- `pytest tests/ -v --tb=short` — full suite green
- Agent runs for 2+ hours without crashing (or overnight if possible)
- Dashboard stays responsive with full dataset
- Add a fake IPO ticker to YAML, confirm Strategy 4 activates correctly
- Remove a ticker from YAML, confirm agent handles gracefully on next cycle
- All open questions from the bottom of this doc that affect implementation have been resolved or documented

---

### Session 7 — Setup Quality Scorecard + composite grading

**Goal:** Turn each actionable signal into a *graded setup* by running the 8 computable confirmations (trend, earnings proximity, volume, relative strength, resistance/headroom, risk/reward, leading layer, AI breadth) and rolling them into a quality grade + action. Surface the composite in alerts and the dashboard. See the "Setup Quality Scorecard" section above for the conceptual spec.

**Build:**
- `src/core/levels.py` — `nearest_resistance(df, price)` from recent swing highs + ATH; `suggested_stop(df, signal)` (below the relevant 21/50 EMA or recent swing low, ATR-aware); `risk_reward(entry, stop, target)`.
- `src/core/benchmarks.py` — fetch SPY/QQQ/SMH (configurable) through the `data.fetch_prices` seam (cached); `relative_strength(ticker_df, bench_df, lookback)` → N-day return delta + outperform flag.
- `src/core/earnings.py` — `days_to_earnings(ticker)` via yfinance (`get_earnings_dates` / `calendar`), cached daily; returns `None` gracefully when unavailable.
- `src/core/market.py` — cycle-level context from all signals: `breadth(signals)` (bullish / neutral / bearish counts) and `layer_leadership(signals, watchlist)` (rank layers by aggregate confidence / entry density).
- `src/core/scorecard.py` — `Check` (name, status pass/warn/fail/na, value, detail), `Scorecard` (checks + weighted `score` + `action`); `build_scorecard(signal, df, ctx)` assembles checks 1–8. Pure/deterministic given its inputs (price df, benchmark data, earnings date, market context).
- Integrate into `signals.py`: the orchestrator computes market context once per cycle, attaches a scorecard to each **actionable** signal, stores a compact summary in the signal/alert `details`, and folds the grade into alert sorting (grade, then confidence).
- `agent/notify.py` — alerts render the composite scorecard block (format in the section above).
- Dashboard — scorecard panel on the **Chart** page; **Overview** gains a `Quality` / `Action` column and a small **breadth + leading-layers** header widget; new `components/scorecard.py` renderer.
- `config.py` — `min_risk_reward` (2.0), `earnings_buffer_days` (5), `rs_lookback` (20), `rs_benchmarks` (["SPY","QQQ","SMH"]), `resistance_lookback`, `low_headroom_pct` (3.0), breadth thresholds, per-check weights, grade cutoffs.
- Tests: `test_levels.py`, `test_benchmarks.py`, `test_market.py`, `test_scorecard.py` (synthetic, deterministic).

**Verify before moving on:**
- Scorecard for NVDA prints all 8 checks (pass/warn/fail) and a final action.
- R:R, nearest resistance, and suggested stop are sane on NVDA / VRT / RDW / TXN.
- Relative strength flips correctly for a synthetic outperformer vs a laggard.
- `days_to_earnings` returns a sane count (or graceful `None`) for a real ticker.
- Breadth counts + layer-leadership ranking computed across the watchlist.
- `python -m src.agent --once` alerts now show the composite block; dashboard shows Quality + breadth.
- `pytest tests/ -v` and `mypy --strict` green.

---

### Session 8 — Evidence layer: historical edge + catalysts

**Goal:** Add the two evidence checks — historical win-rate for the *exact* setup, and recent catalysts — so the final alert is backed by base rates and a reason for the move. Both degrade gracefully (status `n/a`, never fail the cycle) when data is thin.

> **Resolved 2026-05-29:** (1) Backtest **occurrences are counted on the transition into a status** (matches the alert model), with **close-to-close** forward returns and "win" = positive return. (2) Backtest window = **3 years** (`backtest_history_period="3y"`); headline horizon = **20-day** (all of 5/10/20 shown). (3) Historical-edge grade: **≥60% win = pass, 50–60% = warn, <50% = fail**, `n/a` below the minimum sample. (4) **Catalysts grade ONLY on confirmed earnings beat/miss** (reported vs estimate EPS) — **raw headlines never move the grade** (no NLP). Headlines are surfaced as context ("why is it moving?"). *Guidance changes have no free structured source, so they're shown as context only when they appear in headlines, not graded.* (5) Backtest replays via the cheaper `strategy.classify` (no candlestick detection); first run is slow per setup, then served from the `backtest_stats` cache.

**Build:**
- `src/core/backtest.py` — historical signal replay: for a (ticker, strategy, status), fetch 3y daily history, replay `strategy.classify` bar-by-bar to find **transitions into** that status, and measure forward 5/10/20-day close-to-close returns → per-horizon `win_rate`, `avg_return`, `n`. Cache in a `backtest_stats` table; refresh when older than `backtest_refresh_days`.
- `src/core/news.py` — recent headlines via yfinance `Ticker.news` (last `news_days`, default 7) → `[{title, publisher, published, link}]` (context only); plus `earnings_beat(ticker)` from `get_earnings_dates` (reported vs estimate EPS) → `"beat" | "miss" | "inline" | None`. **No NLP / sentiment.** Returns "No known catalyst" when empty.
- Extend `scorecard.py` with check 9 (historical edge — graded on the 20-day win rate) and check 10 (catalyst — graded **only** on earnings beat/miss: beat=pass, miss=warn, else `n/a`). Both additive; `n/a` when data is thin.
- `storage.py` — `backtest_stats` table (ticker, strategy, status, horizon, n, wins, win_rate, avg_return, computed_at) + read/write helpers.
- Dashboard — **Chart** page shows the historical-edge stat + a recent-headlines list; **Alerts** shows win-rate + top catalyst; composite alert gains the two rows.
- `config.py` — `backtest_history_period` ("3y"), `backtest_horizons` ([5,10,20]), `backtest_primary_horizon` (20), `backtest_min_occurrences` (5), `backtest_refresh_days` (7), `backtest_win_pass_pct` (60), `backtest_win_warn_pct` (50), `news_days` (7), `news_max_items` (5).
- Tests: `test_backtest.py` (synthetic history with engineered forward outcomes → known win rate), `test_news.py` (mocked yfinance `news` / earnings).

**Verify before moving on:**
- Backtest for NVDA `AT_21_EMA` over the configured window returns `n`, win rate, avg forward return; result cached and reused on the next call.
- `news.py` returns recent headlines for an active name (or "No known catalyst"); earnings-beat heuristic computes for a name with earnings history.
- Composite alert now includes **Historical edge** and **Catalyst** rows.
- Edge cases: no earnings data, no news, history below `backtest_min_occurrences` → all degrade to `n/a` without breaking the cycle.
- `pytest tests/ -v` and `mypy --strict` green; a full `--once` cycle still completes in reasonable time (backtest is cached).

---

### Session 9 — Trade Due Diligence Dossier (bull/bear case + trade plan)

**Goal:** Synthesize everything — the four strategy signals, the Session 7 scorecard, Session 8 evidence, and benchmark/market context — into one per-candidate **dossier** that forces a balanced bull-vs-bear case and a concrete trade plan, anchored by *"why should I NOT buy this?"* See the "Trade Due Diligence Dossier" section above for the conceptual spec. Builds on Session 7; enriched by Session 8 when present. **The bear case is never empty on a graded setup**, and the position plan is **informational only — never automated**.

**Build:**
- `src/core/indicators.py` — add `EMA_200`, distance-to-200 %, `above_200_ema`; bump `history_bars` to ~260 so the 200 EMA is meaningfully warmed.
- `src/core/benchmarks.py` — `above_own_ema(df, span=21)` and `market_regime(benchmarks)` → QQQ / SMH above-their-own-21-EMA flags.
- `src/core/levels.py` — `strategy_stop(df, signal, metrics)` (context-aware: 21 EMA vs range low vs swing low) and `invalidation_text(signal)`.
- `src/core/dossier.py` — `Dossier` (reasons_to_buy, reasons_not_to_buy, strongest_bull, strongest_bear, confluence, extension, trend_alignment, market_regime, trade_plan, manual_catalyst_checks) and `build_dossier(ticker, signals, scorecard, ctx)`. Pure given its inputs. Reasons are derived from the scorecard's pass/warn/fail checks plus the dossier-specific checks. The **position plan** (sizing tier from grade, add-levels, profit targets) is suggestion-only.
- `src/core/signals.py` — after grading, build one dossier per ticker that has an alertable signal (using all of that ticker's strategy signals + the best signal's scorecard); store a compact summary in `details` or a `dossiers` table keyed `(ticker, date)`.
- `src/agent/notify.py` — alerts include the **Reasons NOT to buy** (top bear factors) next to the grade.
- Dashboard — a **Dossier panel** on the **Chart** page (two-column Reasons to buy / NOT to buy + trade plan + confluence + regime); **Overview** can show the single strongest bear factor.
- `config.py` — `ema_chasing_pct` (15.0), grade→sizing-tier mapping, `regime_ema_span` (21), `profit_target_pcts` ([10, 15]), `dossier_max_reasons`.
- Tests: `test_dossier.py` (synthetic — bull/bear split, confluence count, trend alignment, regime, context-aware stop + invalidation per strategy), plus `EMA_200` and benchmark-regime tests.

**Verify before moving on:**
- Dossier for a real name lists both reasons to buy *and* reasons NOT to buy (bear case never empty on a graded setup).
- Strategy confluence count matches the ticker's actual signals.
- Trend alignment uses both the 50 and 200 EMA; market regime reflects QQQ / SMH vs their 21 EMA.
- Trade plan: the stop differs by setup type; invalidation text is present; the sizing tier follows the grade.
- Composite alert and the Chart dossier panel show the bull/bear case.
- `pytest tests/ -v` and `mypy --strict` green.

---

### Session 10 — Market-Regime Gate + Automatic Disqualifiers

**Goal:** Stop low-quality alerts *at the source*. A market-regime read and a set of hard disqualifier rules suppress (or downgrade) alerts regardless of how good the chart looks — "maximize odds, not signal count." The single highest-leverage filter in the whole system.

**Build:**
- `src/core/regime.py` — `market_regime(benchmarks)` → `RISK_ON | NEUTRAL | RISK_OFF` from SPY / QQQ / SMH vs their **50 EMA** (RISK_OFF if ≥ `regime_risk_off_fails` of 3 are below; RISK_ON if all above; else NEUTRAL). Returns per-index flags + the label. (Distinct from Session 9's informational 21-EMA regime line; this is the canonical gating regime — Session 9 may reuse it.)
- `src/core/gating.py` — `disqualifiers(signal, scorecard, regime) -> list[str]` of tripped hard rules; each rule individually toggleable in config. Defaults: price **below the 50 EMA**, earnings within `dq_earnings_days` (3), relative strength **below market**, **declining volume**, and (optional) **R:R below `dq_min_rr`**. `disqualifier_mode`: `"suppress"` (no alert) or `"downgrade"` (alert fires but grade is capped and flagged).
- Integrate into `signals.py`: compute the regime once per cycle (from the benchmarks already fetched); run every would-be alert through `disqualifiers`. Suppressed setups are still **recorded as signals** (visible in the dashboard) but fire **no notification**. In RISK_OFF, raise the alert bar (`risk_off_min_stars`) and discount aggressive buys.
- `agent/notify.py` — alerts carry a **regime banner**; note when running in RISK_OFF.
- Dashboard — a **regime badge** in the Overview header (🟢 RISK_ON / 🟡 NEUTRAL / 🔴 RISK_OFF) and a "disqualified" marker on setups that were suppressed.
- `config.py` — `regime_ema_span` (50), `regime_risk_off_fails` (2), `disqualifier_mode` ("suppress"), per-rule toggles (`dq_below_50ema`, `dq_earnings_days` 3, `dq_rs_below_market`, `dq_declining_volume`, `dq_min_rr` off by default), `risk_off_min_stars`.
- Tests: `test_regime.py` (label from synthetic index sets), `test_gating.py` (each rule trips → suppress/downgrade).

**Verify before moving on:**
- Regime label correct for synthetic SPY/QQQ/SMH sets (all-above → RISK_ON; 2-below → RISK_OFF).
- A setup below the 50 EMA or with earnings in 2 days is **suppressed** (no alert) in "suppress" mode, but still stored.
- RISK_OFF raises the alert bar (fewer / de-prioritized alerts) and shows in the dashboard banner.
- `pytest tests/ -v` and `mypy --strict` green.

---

### Session 11 — Composite Score + Cross-Sectional Ranking + Rotation + Thesis

**Goal:** Move from grading each stock in isolation to ranking *every* name against each other — "is this the best place for my next dollar?" Produce a 0–100 composite, rank the whole watchlist, suggest an allocation, and surface layer rotation + AI-thesis health.

**Build:**
- `src/core/scoring.py` — `composite_score(...)` → **0–100**, weighted by category (Technical 30 / Relative-strength 20 / Volume-Accumulation 15 / Market-regime 10 / Earnings 10 / Value-chain leadership 10 / Catalyst 5; weights in config). Maps the existing scorecard checks (+ Session 12 inputs when present) to category subscores; degrades gracefully when a category is `n/a`.
- `src/core/ranking.py` — cross-sectional: `rs_rank(...)` (percentile rank of each name's relative strength → "top 5%"); `rank_opportunities(scored)` (ordered best→worst with composite scores → opportunity-cost view, "pass on ETN, better exist"); `suggest_allocation(top_n)` (normalized % weights across the top N, proportional to score).
- `src/core/market.py` (extend) — `layer_strength()` (0–100 per value-chain layer) and `layer_rotation(history)` (Δ in layer strength vs a prior window → money flowing in/out, ▲/▼); `thesis_health(leaders)` → `Healthy | Deteriorating` from whether the key leaders hold their 50 EMA.
- `storage.py` — a small `daily_scores` / `layer_strength` table so rotation (Δ over time) and a score history exist.
- Integrate: orchestrator computes the composite per gradeable signal + the cross-sectional ranks; alerts/notify include **score + rank** ("NVDA 91/100 · #2 of 41"). *(Stretch: weight the Session 8 historical win-rate by the current regime — regime-conditional base rates.)*
- Dashboard — **Overview** sortable by composite (new default), a **"Top opportunities today"** panel with suggested allocation %, and the **Value-Chain** page gains a layer-strength bar + rotation arrows + a thesis-health banner.
- `config.py` — category weights, `top_opportunities_n` (5), `rotation_lookback_days`, thesis-leaders list (or derive from capex exposure / market cap).
- Tests: `test_scoring.py` (subscores + 0–100), `test_ranking.py` (percentile rank, ordering, allocation sums ~100%), layer rotation + thesis flips.

**Verify before moving on:**
- Composite 0–100 computed; category subscores sum correctly; `n/a` categories handled.
- Cross-sectional RS rank puts the strongest names in the top percentile.
- Opportunity ranking orders best→worst; suggested allocation sums to ~100%.
- Layer strength + rotation: a layer with improving signals scores higher / shows ▲.
- Thesis health flips to "Deteriorating" when the leaders lose their 50 EMA.
- Dashboard sorts by score and shows the Top-opportunities + allocation panel.
- `pytest tests/ -v` and `mypy --strict` green.

---

### Session 12 — Deeper Signals (institutional intent + trend context)

**Goal:** Add the institutional-accumulation and trend-context signals that feed the composite score and dossier — the inputs that tell you *whether big money is actually behind the move* and *what stage the stock is in*.

**Build:**
- `src/core/accumulation.py` — OBV, Accumulation/Distribution line, up-vs-down-volume ratio, and close-position-in-range; an `accumulation_score` (e.g., OBV trend up + A/D rising + closes near highs = institutions accumulating). Feeds the Volume-Accumulation category.
- `src/core/multitimeframe.py` — resample daily → weekly; `weekly_trend(df)` (above/below the 30-week MA + slope) → `uptrend | downtrend | neutral`; an alignment flag with the daily setup (weekly-uptrend + daily pullback = stronger; weekly-downtrend = weaker).
- `src/core/stage.py` — Weinstein **Stage 1–4** classification (basing / advancing / topping / declining) from price vs the 30-week MA and its slope. A `AT_21_EMA` pullback in Stage 2 ≠ the same in Stage 4.
- `src/core/indicators.py` — add **ATR** (and `EMA_200` if Session 9 hasn't already); express extension/crowding **in ATRs** (volatility-normalized, so RDW and TXN are judged on their own scale); a `crowding_score` (% above the 200 EMA + recent run-up, ATR-normalized).
- `src/core/watchlist.yaml` + `watchlist.py` — add a curated **`capex_exposure`** (0–100) per ticker (how directly the name benefits from AI capex); loaded and fed into scoring as the AI-capex factor.
- Integrate: these become composite-score inputs and dossier/scorecard context (e.g., **downgrade a Stage-4 pullback**, reward weekly-uptrend alignment, penalize high crowding).
- `config.py` — accumulation lookbacks, `weekly_ma_weeks` (30), stage thresholds, `atr_window` (14), crowding thresholds.
- Tests: `test_accumulation.py` (accumulation vs distribution synthetic series), `test_multitimeframe.py` (weekly resample + alignment), `test_stage.py` (Stage 2 vs Stage 4), ATR/crowding.

**Verify before moving on:**
- OBV / A-D / accumulation score behave correctly on synthetic accumulation vs distribution data.
- Weekly resample is correct; the alignment flag matches the weekly trend.
- Stage classification: a synthetic Stage-2 advance vs a Stage-4 decline classify correctly.
- ATR-normalized extension distinguishes a volatile name from a calm one at the same % distance.
- `capex_exposure` loads from YAML and moves the composite score.
- `pytest tests/ -v` and `mypy --strict` green.

---

> **Read first — what Sessions 13–14 are and why they're different:**
> Sessions 1–12 make the agent a great *scanner and grader* of individual setups. None of them
> change the fact that the agent is **stateless about exposure** — it finds setups but has no
> concept of "how much should I be invested right now" or "which of my held names should I cut."
> Beating the index requires the one thing the S&P 500 structurally cannot do: **vary total
> exposure and concentrate into the strongest names.** That needs **portfolio state**, which this
> CLAUDE.md previously deferred to the v2 track. Session 13 pulls the *exposure-management* half
> of that v2 work forward, because it is the actual source of edge. Position-level exit management
> for real holdings stays in v2.
>
> **The edge, stated plainly:** the index is always 100% invested in ~500 names. This agent can be
> 100% invested in its 6 best names during RISK_ON and 30%/cash during RISK_OFF. That asymmetry —
> dynamic exposure + concentration — is the realistic alpha. Entry precision is not.
>
> **Everything here is a SIMULATED / PAPER portfolio.** It produces target weights and rebalance
> *suggestions* against a hypothetical balance. It never auto-executes. (Live order routing stays
> permanently out of scope.)
>
> **This is unproven until Session 14 (backtest) validates it.** Aggressive concentration and a
> regime dial look great in a bull stretch and can hurt in whipsaw/bear regimes. Do not trust this
> with a real dollar before the walk-forward backtest. Build 13, then immediately build 14.

---

### Session 13 — Portfolio Exposure Management

**Goal:** Turn the agent from a setup *scanner* into a *portfolio constructor* that can beat the
index via the only durable levers available to a concentrated thematic book: **(1) dynamic total
exposure** (the cash option the index lacks), **(2) conviction-weighted concentration** into the
top-ranked names, and **(3) relative-strength rotation** that cuts laggards fast. All paper-only;
all suggestions, never auto-executed.

**The three mechanisms:**

1. **Regime-as-a-dial (exposure.py).** Promote the Session 10 regime from an alert filter to a
   portfolio-level exposure target:
   - `RISK_ON` → `target_exposure_on` (default 100% invested)
   - `NEUTRAL` → `target_exposure_neutral` (default 60%)
   - `RISK_OFF` → `target_exposure_off` (default 30%; configurable to 0% for fully defensive)
   - **Hysteresis (critical, prevents whipsaw):** require the regime label to persist for
     `regime_confirm_days` (default 3 trading days) before changing the exposure target. A
     one-day flip does NOT move the dial. This is the single most important guard — a laggy gate
     that flip-flops will bleed the account on whipsaws and is how this kind of system most often
     underperforms buy-and-hold.

2. **Conviction sizing (sizing.py).** Within the target exposure, weight positions by composite
   score (Session 11), not equal-weight:
   - Take the top `max_positions` names (default 6) by composite score that have a gradeable,
     non-disqualified setup.
   - Weight ∝ composite score, normalized to the current exposure target.
   - **Concentration cap:** no single name exceeds `max_position_pct` (default 25%) — prevents one
     RDW-style moonshot-or-disaster from dominating the book.
   - **Minimum weight floor:** drop names whose normalized weight falls below `min_position_pct`
     (default 5%) — avoids dust positions that just add turnover.

3. **Relative-strength rotation (sizing.py).** Decide what to hold vs. cut:
   - **Enter:** a name breaking into the top `max_positions` by composite with a non-disqualified,
     ≥`min_grade` setup.
   - **Exit:** a held name that (a) falls below `exit_rank` (default: out of top 10), OR (b) loses
     its 50 EMA, OR (c) trips a Session 10 disqualifier. Cut losers fast; let winners ride.
   - **Hold band:** to limit churn, a held name in ranks `max_positions+1 .. exit_rank` is *held,
     not added to* — it only exits when it breaches `exit_rank`. This hysteresis on names mirrors
     the hysteresis on regime.

**Turnover / cost discipline (woven through):**
- **Rebalance cadence:** `rebalance_cadence` (default `"weekly"`, not daily) — recompute targets
  on a schedule, not every signal. Daily rebalancing churns the account to death.
- **No-trade band:** only generate a rebalance suggestion when a target weight differs from the
  current weight by more than `rebalance_threshold_pct` (default 3%). Small drifts are ignored.
- Rationale baked into the doc: live momentum returns historically ran ~half their paper level
  after costs — turnover is a tax, so the design minimizes it.

**Build:**
- `src/core/portfolio.py` — `PaperPortfolio` (cash + positions {ticker, shares, entry, weight},
  hypothetical NAV from latest closes); `current_weights()`, `apply_targets(targets)` (records a
  rebalance event, paper-only), persisted in a `portfolio` + `portfolio_history` SQLite table.
- `src/core/exposure.py` — `target_exposure(regime_history)` with the hysteresis rule → a single
  0.0–1.0 invested fraction.
- `src/core/sizing.py` — `target_weights(ranked_signals, exposure, held)` implementing conviction
  sizing + concentration caps + RS rotation + hold-band + no-trade-band. Pure/deterministic.
- `src/core/signals.py` — after ranking, compute the exposure target, build target weights, diff
  against the paper portfolio, and emit **rebalance suggestions** ("trim NVDA 28%→25%, exit GEV,
  add LITE 8%"). Stored + shown; never executed.
- `src/agent/notify.py` — a daily/weekly **portfolio summary** alert: current exposure %, regime,
  holdings with weights, and any rebalance suggestions.
- Dashboard — a new **Portfolio** page: current paper NAV vs a $5,000 (configurable) start, the
  exposure dial (🟢/🟡/🔴 + %), current holdings with weights and composite scores, rebalance
  suggestions, and a NAV-vs-VOO line chart (VOO fetched through the existing `data.fetch_prices`
  seam). This VOO overlay is the whole point — every view benchmarks against the index.
- `config.py` — `paper_start_balance` (5000), `target_exposure_on/neutral/off` (1.0/0.6/0.3),
  `regime_confirm_days` (3), `max_positions` (6), `max_position_pct` (0.25), `min_position_pct`
  (0.05), `exit_rank` (10), `min_grade` ("DECENT"), `rebalance_cadence` ("weekly"),
  `rebalance_threshold_pct` (0.03).
- Tests: `test_exposure.py` (hysteresis: a 1-day flip does NOT move the dial; a 3-day persistent
  flip does), `test_sizing.py` (conviction weights sum to exposure, concentration cap holds,
  laggard below exit_rank is cut, hold-band name is kept, no-trade-band suppresses tiny rebalances),
  `test_portfolio.py` (NAV math, apply_targets bookkeeping).

**Verify before moving on:**
- Exposure dial: synthetic RISK_OFF for 1 day → no change; persists 3 days → exposure drops to the
  configured floor. No whipsaw on single-day flips.
- Conviction sizing: top-6 by composite, weights ∝ score, none exceed 25%, sum to the exposure
  target, dust positions dropped.
- Rotation: a held name that loses its 50 EMA or falls past rank 10 produces an EXIT suggestion; a
  name drifting within the hold band is kept.
- No-trade band: a 1% target drift produces no suggestion; a 5% drift does.
- Dashboard Portfolio page shows paper NAV, exposure dial, holdings, suggestions, and the VOO
  overlay.
- `pytest tests/ -v` and `mypy --strict` green.

**Honest guardrails written into the session:**
- This is a SINGLE-THEME book. Dynamic exposure + concentration can beat the index over a cycle,
  but the dominant variable remains whether the AI theme outperforms. The agent times and
  concentrates the theme; it does not diversify away from it.
- The regime dial's value depends entirely on the gate being good. A whippy gate underperforms
  buy-and-hold. The hysteresis is mandatory, and the gate's behavior must be inspected in the
  Session 14 backtest across a real bear market before trusting it.
- Concentration cuts both ways: it's why the book can beat the index and why its drawdowns can be
  deeper. The `max_position_pct` cap is the protection; do not raise it without backtest evidence.
- Paper-only. No live execution, ever, in this project.

---

### Session 14 — Walk-Forward Backtest vs VOO (the verdict)

**Goal:** The only session that answers "does this beat the S&P 500?" Run the *entire* pipeline
(strategies → scorecard → gating → composite → exposure → sizing → rotation) over 3–5 years of real
daily bars, walk-forward, and measure the paper portfolio against VOO net of estimated costs —
through at least one real drawdown.

**Build:**
- `src/core/backtest_portfolio.py` — replay the full system bar-by-bar over `backtest_years`
  (default 5) of real history: at each rebalance date, reconstruct the agent's targets *using only
  data available up to that date* (no lookahead), apply turnover costs (`cost_per_trade_bps`,
  default 10 bps round-trip + slippage), and track paper NAV.
- Metrics vs VOO over the same window: total return, CAGR, **max drawdown**, **Sharpe**, **Sortino**,
  volatility, % of months beating VOO, longest underperformance streak, turnover, and cost drag.
- Regime-conditional breakdown: performance in RISK_ON vs RISK_OFF months (does the dial actually
  add value, or just reduce return?).
- A NAV-vs-VOO equity curve + drawdown chart on a new dashboard **Backtest** tab.
- `config.py` — `backtest_years` (5), `cost_per_trade_bps` (10), `slippage_bps` (5).
- Tests: no-lookahead assertion (targets at date T use only data ≤ T), cost application, metric math.

**Verify before moving on:**
- Backtest completes over the full window with no lookahead.
- Reports total return, CAGR, max drawdown, Sharpe/Sortino, % months > VOO — all vs VOO net of costs.
- The equity curve spans at least one real correction; inspect how the exposure dial behaved there.
- **The honest read:** if the system does not beat VOO on a risk-adjusted basis (Sharpe) net of
  costs across the full window including a drawdown, that is the answer — do not deploy capital.
  A smoother ride at a lower return is a legitimate outcome; a higher return with far deeper
  drawdowns is not a win. Let the numbers decide, not the narrative.
- `pytest tests/ -v` and `mypy --strict` green.

---

### v2 / Future — Portfolio-aware decision support (deferred, not yet a buildable session)

> **Note:** Exposure dialing, conviction sizing, concentration caps, and RS rotation are **no longer
> deferred** — they're **Session 13** (paper portfolio) + **Session 14** (walk-forward validation vs
> VOO). What remains below is the half that requires knowing your **real** positions.

Sessions 1–14 build and validate a **paper** portfolio constructor — but it's still stateless about
what you *actually own*. The remaining leap needs a **holdings input** (a positions file/config:
`ticker, entry, size, date`) plus a light **trade journal**. Once the agent knows your real book it
can answer the questions a paper portfolio can't:

- **Position-level exit management for real holdings** — the under-served half of trading:
  `HOLD / TRIM / TAKE-PROFIT / EXIT` per *actual* position (e.g., close below the 50 EMA → EXIT;
  +X% → TRIM; trailing stop), plus **opportunity cost vs. what you own** ("is this a better dollar
  than a name you already hold?"). Session 13 rotates a *paper* book; this manages the *real* one.
- **Trade journal** — record "I bought this alert at $X" and track real outcomes (see open
  question #17); the raw material for calibration.
- **Bayesian probability of success** — a calibrated win probability blended from setup type +
  **regime-conditional** historical win-rate + RS + earnings proximity, replacing/augmenting the
  star rating.

These depend on a holdings store + the trade journal and some calibration data. **Scope when
requested** — they change the agent from a watchlist scanner into a portfolio co-pilot.

---

## Watchlist (AI data center value chain)

Organized by value chain layer (per Silicon Analysts / Spear Invest research). Stored in `src/core/watchlist.yaml`, hot-reloaded by the agent on next cycle. Each ticker has a `layer` tag for filtering and grouping in the dashboard.

**Layer 1 — GPU / Accelerator Makers** (the compute core)
- NVDA (NVIDIA) — 75-86% DC AI market share, $115B DC revenue FY2025
- AMD — MI-series accelerators, ~$10B DC revenue, approaching 30%+ server CPU share
- INTC (Intel) — Gaudi line, Falcon Shores; weakened but still relevant

**Layer 2 — ASIC Co-designers** (the hyperscaler chip enablers)
- AVGO (Broadcom) — ~60% of custom ASIC co-design market, ~$12B AI revenue. Google spends ~$8B/yr with AVGO on TPU dev
- MRVL (Marvell) — ~35% of ASIC co-design market, partners with AWS + Microsoft

**Layer 3 — Semiconductors (analog, memory, IP)**
- TXN (Texas Instruments) — analog, power management
- MU (Micron) — HBM memory (bottleneck, 78% CAGR to 2027)
- ASML — lithography monopoly
- ARM — IP licensing, ~20% DC CPU share (up from 5% in 2020), NVIDIA's own Vera Rubin is ARM-exclusive
- ADI (Analog Devices) — power management, 800 VDC partner
- ON (onsemi) — power semis, 800 VDC partner
- IFNNY (Infineon) — power management, 800 VDC partner
- RNESY (Renesas) — power management, 800 VDC partner

**Layer 4 — Networking & Interconnects** (the emerging bottleneck per Silicon Analysts)
- ANET (Arista) — data center switching
- CIEN (Ciena) — optical networking
- CRDO (Credo) — high-speed connectivity
- APH (Amphenol) — custom-engineered NVLink spine cartridge, IT Datacom +134%. AI racks need 10-36x more fiber
- TEL (TE Connectivity) — backup NVLink supplier, DAC/AEC cables
- GLW (Corning) — optical fiber, $6B Meta deal, sold out through 2026
- LITE (Lumentum) — EML lasers inside most 800G/1.6T transceivers, Q1 +58% YoY
- COHR (Coherent) — 800G/1.6T transceivers, InP laser leader

**Layer 5 — Power & Electrical** (outside the rack, 20-40% CAGR)
- VRT (Vertiv) — cooling + power, top 3 outside-the-rack player
- ETN (Eaton) — electrical distribution, 800 VDC partner
- GEV (GE Vernova) — turbines, grid infrastructure
- ABBNY (ABB) — electrification, 800 VDC partner
- SIEGY (Siemens) — industrial electrification, 800 VDC partner
- PWR (Quanta Services) — grid construction / electrical contracting

**Layer 6 — Cooling & Thermal** (40% CAGR per Spear Invest)
- NVT (nVent) — thermal management, liquid cooling

**Layer 7 — OEMs / Server Builders**
- SMCI (Supermicro) — largest AI server ODM by GPU-server volume
- DELL (Dell) — PowerEdge AI servers, $10B AI pipeline
- HPE (Hewlett Packard Enterprise) — AI servers + HPC (Cray)

**Layer 8 — Data Center REITs** (the physical footprint)
- EQIX (Equinix)
- DLR (Digital Realty)

**Layer 9 — Space & Adjacent**
- RDW (Redwire) — space infrastructure
- RKLB (Rocket Lab) — launch + space systems
- ASTS (AST SpaceMobile) — satellite broadband
- LUNR (Intuitive Machines) — lunar infrastructure

**Layer 10 — Pre-IPO Proxies / AI Model Layer** (watch for IPO announcements)
- MSFT (Microsoft) — exclusive OpenAI inference partner, Azure $100B+ run-rate
- GOOG (Google) — Gemini/TPU, $46B cloud run-rate
- AMZN (Amazon) — AWS Trainium, $115B cloud run-rate
- META — 600K+ GPUs, MTIA custom inference chip

These hyperscalers are included because they are the **largest AI capex spenders ($380B+ combined in 2025)** and their spending directly drives revenue for every other layer. They also serve as proxies before Anthropic/OpenAI IPO — when the IPO drops, watch for rotation out of these into the actual listings.

Watchlist should be **trivially editable** — single YAML file, hot-reloaded by the agent on next cycle. Each entry: `{ticker, name, layer, notes}`.

---

## Entry strategies

The agent runs **four strategies in parallel** for every ticker on every evaluation cycle. Each strategy is a separate module in `src/core/strategies/`. A ticker can trigger multiple strategies simultaneously — the dashboard shows all active signals.

### Strategy 1: EMA Pullback (works for trending, non-parabolic stocks)

**When to use:** Stock is in an uptrend but not wildly extended. Typical for mid-cap or early-cycle names that haven't gone parabolic yet (e.g., CIEN, TXN, PWR, some REITs).

**Logic:**
1. Pull last ~200 daily candles via `yfinance`
2. Compute `EMA_9`, `EMA_21`, `EMA_50` on closing prices
3. Distance from current price to each EMA as percentage: `dist_pct = (close - ema) / ema * 100`
4. Classify:
   - **EXTENDED** — price > 8% above 21 EMA
   - **APPROACHING_9** — price within 2% of 9 EMA from above
   - **AT_9_EMA** — price touched or crossed 9 EMA intrabar
   - **APPROACHING_21** — price within 3% of 21 EMA from above
   - **AT_21_EMA** — price touched or crossed 21 EMA — **primary EMA alert**
   - **BELOW_21_EMA** — broken below; trend may be invalidated
5. Alert on transitions into `AT_9_EMA` or `AT_21_EMA`
6. Optional trend filter: only alert if price > 50 EMA (see open questions)

### Strategy 2: Breakout from Consolidation / Flag (works for extended stocks)

**When to use:** Stock has run up big, then goes sideways for 2–6 weeks forming a "flag" or "base." The consolidation IS the entry — breakout on volume is the signal. This is how most big winners are traded in strong bull markets.

**Logic:**
1. Identify consolidation: price has been within X% range (default 8%) for N+ days (default 10 trading days)
2. Compute the consolidation range: `high_of_range`, `low_of_range`
3. Breakout = close above `high_of_range` on volume > 1.5x 20-day average volume
4. Classify:
   - **CONSOLIDATING** — in a base/flag, waiting
   - **BREAKOUT** — broke above range on volume — **alert**
   - **BREAKDOWN** — broke below range on volume — **warning, thesis may be broken**
   - **NO_PATTERN** — not consolidating, not flagging
5. Alert on `BREAKOUT` transitions

### Strategy 3: Percentage Pullback from ATH (simplest strategy for hot names)

**When to use:** Stock is at or near all-time highs. Forget EMAs — just buy any meaningful dip in a confirmed uptrend. VRT drops 10% from $380? That's the entry. Simple and it actually triggers for parabolic stocks.

**Logic:**
1. Compute ATH from last 52 weeks (or all available history)
2. Compute `pullback_pct = (ath - close) / ath * 100`
3. Classify:
   - **AT_ATH** — within 1% of all-time high
   - **MINOR_PULLBACK** — 3–5% below ATH
   - **ENTRY_ZONE** — 5–10% below ATH — **primary alert** (best risk/reward)
   - **DEEP_PULLBACK** — 10–20% below ATH — **secondary alert** (could be trend change)
   - **CORRECTION** — 20%+ below ATH — not a dip buy anymore
4. Only alert if stock made a new ATH within the last 30 trading days (confirming the uptrend is active, not a stale high from months ago)

### Strategy 4: IPO Base (specifically for Anthropic / OpenAI when they list)

**When to use:** After a major AI company IPOs. New IPOs typically spike on day 1, then consolidate for 2–8 weeks forming an "IPO base." The breakout from that base on volume is the classic entry. This strategy is dormant until an IPO ticker is added to the watchlist.

**Logic:**
1. Detect IPO: stock has < 60 trading days of history
2. Mark the initial high (first 5 days of trading) as `ipo_high`
3. Identify consolidation below `ipo_high` (similar to Strategy 2 but with IPO-specific parameters)
4. Breakout = close above `ipo_high` on volume > 1.5x average
5. Classify:
   - **IPO_FRESH** — less than 5 days of trading, too early
   - **IPO_BASING** — consolidating below initial high, wait
   - **IPO_BREAKOUT** — broke above IPO high on volume — **alert**
   - **IPO_FAILED** — dropped 25%+ from IPO high, avoid
6. Alert on `IPO_BREAKOUT`

### Strategy selection per ticker

The agent doesn't pick one strategy — it evaluates **all four** for every ticker. But the dashboard highlights which strategy is most relevant based on the stock's current state:

- Stock 30% above 21 EMA → Strategy 2 (consolidation breakout) or Strategy 3 (ATH pullback) are primary; Strategy 1 is grayed out ("EMA pullback: not actionable, stock is extended")
- Stock within 5% of 21 EMA → Strategy 1 is primary
- Stock just IPO'd → Strategy 4 is primary
- Stock breaking out of a 3-week flag → Strategy 2 fires

**All thresholds are configurable** in `config.py` — not hardcoded magic numbers.

---

## Bullish pattern confirmation (quality scoring)

Bullish candlestick patterns are **not a standalone strategy** — they fire too often and are unreliable in isolation. Instead, they serve as a **confirmation layer** that attaches a confidence score to every signal from the four strategies above.

A signal with pattern confirmation = higher quality. A signal without = still valid, just lower confidence. The dashboard shows this as a confidence badge (e.g., ⭐⭐⭐ vs ⭐).

### Candlestick patterns to detect (1–3 bars)

Detect using `pandas-ta` candlestick functions (wraps TA-Lib logic):

- **Bullish Engulfing** — large green candle fully engulfs previous red candle. Strong reversal signal at support.
- **Hammer** — small body at top, long lower wick (2x+ body). Shows buyers stepping in after a dip.
- **Morning Star** — 3-bar pattern: red candle → small-body candle (indecision) → large green candle. Classic bottom reversal.
- **Three White Soldiers** — 3 consecutive green candles with higher closes, each opening within the previous body. Strong bullish momentum.
- **Doji at Support** — tiny body (open ≈ close) appearing at an EMA or ATH pullback level. Indecision → potential reversal.
- **Piercing Line** — red candle followed by green candle that opens below the prior low but closes above the prior midpoint.

### How confirmation scoring works

After a strategy classifies a ticker's status (e.g., `AT_21_EMA`), the confirmation layer checks the last 3 candles for any bullish patterns:

```
confidence = BASE_SCORE  # from strategy alone

if bullish_engulfing or morning_star:
    confidence += 2  # strong confirmation
elif hammer or three_white_soldiers or piercing_line:
    confidence += 1  # moderate confirmation
elif doji_at_support:
    confidence += 1  # weak but notable

# Cap at 3 stars
stars = min(3, confidence)
```

**Base scores by signal type:**
- `AT_21_EMA` = 1 (good level, needs confirmation)
- `AT_9_EMA` = 1 (good level, needs confirmation)
- `ENTRY_ZONE` (ATH pullback 5-10%) = 1
- `BREAKOUT` (consolidation) = 2 (volume already confirms)
- `IPO_BREAKOUT` = 2 (volume already confirms)

So a `AT_21_EMA` + bullish engulfing = ⭐⭐⭐ (highest confidence), while `AT_21_EMA` alone = ⭐ (valid but unconfirmed).

### What this means for alerts

- ⭐ = Signal active, no pattern confirmation. "VRT approaching 21 EMA."
- ⭐⭐ = Signal + moderate pattern confirmation. "VRT at 21 EMA, hammer formed."
- ⭐⭐⭐ = Signal + strong pattern confirmation. "VRT at 21 EMA, bullish engulfing confirmed. High confidence entry."

Alert priority in notifications scales with stars — ⭐⭐⭐ alerts are louder / more prominent.

---

## Setup Quality Scorecard (decision framework)

> **Guiding principle: a ⭐⭐⭐ signal is the *start* of due diligence, not the final decision.** Detection ("did it touch the 21 EMA?") and pattern confidence answer *whether a setup exists*. The scorecard answers *whether it's worth taking* — and a high-confidence pattern can still be a poor trade (lagging the market, no room to resistance, bad risk/reward, right before earnings). The agent surfaces the candidate; the scorecard is the checklist you'd otherwise run by hand.

Confidence stars answer a narrow question — *"did a candlestick pattern confirm the signal?"* The **scorecard** answers the bigger one: *"is this one of the best opportunities in the AI infrastructure universe right now?"*

After a strategy fires and pattern confidence is attached, the agent runs a fixed checklist of confirmations and rolls them into an overall **quality grade + action**. Each check returns ✅ pass / ⚠️ warn / ❌ fail (plus the underlying value). The scorecard never overrides detection — a low grade still records the signal, it just tells you to pass.

**Computable checks (Session 7):**

1. **Trend** — close vs 50 EMA. Pass above, fail below. *The single most important filter* — below the 50 EMA you're often buying into a downtrend. (Already computed as `metrics.above_50_ema`.)
2. **Earnings proximity** — trading days to next earnings. Warn if within `earnings_buffer_days` (default 5). A perfect setup can be wrecked by an earnings gap.
3. **Volume support** — latest volume vs 20-day average. Pass ≥1.5×, warn ≥1.0×, fail <1.0×. (Already computed as `metrics.vol_ratio`.)
4. **Relative strength** — N-day return vs SPY / QQQ / SMH. Pass if outperforming, fail if lagging badly. (If SPY is +5% and the name is −10%, that's a warning.)
5. **Nearest resistance & headroom** — distance to the nearest swing-high / ATH above price. Low headroom (<~3%) warns: little room to run.
6. **Risk / reward** — entry = close, stop = below the relevant EMA / recent swing low, target = nearest resistance / ATH. Pass if R:R ≥ `min_risk_reward` (default 2.0). Even a high-conviction setup may not be worth taking at 0.75 R:R.
7. **Leading layer** — is this ticker's value-chain layer one of the strongest right now (aggregate confidence / entry density)? Sector leadership matters — money rotating into interconnects vs power is signal.
8. **AI breadth** — health of the whole basket (bullish / neutral / bearish counts). Context: 29/38 bullish is a very different tape than 8/38.

**Evidence checks (Session 8):**

9. **Historical edge** — prior occurrences of this exact (ticker, strategy, status) and the forward 5/10/20-day win rate. Trade base rates, not intuition.
10. **Catalysts** — recent headlines + an earnings-beat heuristic explaining *why* it's moving (free yfinance headlines, no NLP).

The grade aggregates the checks (weighted — Trend and R:R weigh most; thresholds in `config.py`) into an **action**: `HIGH-QUALITY`, `DECENT`, `MARGINAL`, or `AVOID`.

**The upgraded alert (target output):**

```
NVDA ⭐⭐⭐   ENTRY_ZONE
Trend:         Above 50 EMA           ✅
Volume:        1.8x average           ✅
Earnings:      32 days away           ✅
Rel. strength: Outperforming QQQ      ✅
Risk/Reward:   3.4 : 1                ✅
Resistance:    $250 (+15.7% headroom) ✅
AI breadth:    29/38 bullish          ✅
Hist. edge:    74% win (20d, n=18)    ✅   ← Session 8
Catalyst:      Raised guidance         •   ← Session 8
Action:        HIGH-QUALITY SETUP
```

At that point you're not just asking "did it touch the 21 EMA?" — you're asking "is this one of the best opportunities in the whole AI value chain right now?"

---

## Trade Due Diligence Dossier (bull vs bear)

The scorecard grades a setup's *quality*. The **dossier** is the layer above it that turns quality into a *decision* — and guards against confirmation bias. Its anchor is the single most important question:

> **"Why should I NOT buy this stock right now?"**

A detection engine that only lists reasons to buy becomes a confirmation-bias machine. The dossier always surfaces the **bear case next to the bull case**, plus a concrete **trade plan** — so a ⭐⭐⭐ signal is the *start* of due diligence, not the end. It never tells you to trade; it hands you the bull case, the bear case, and the plan, then leaves the call to you.

For each candidate the dossier assembles:

- **Reasons to buy / reasons NOT to buy** — every scorecard *pass* becomes a bull point, every *warn/fail* a bear point, augmented by the dossier-specific checks below. The single strongest of each is highlighted. The bear list is never empty on a graded setup.
- **Strategy confluence** — how many of the four strategies agree (e.g. "2/4: EMA `AT_21_EMA` + ATH `ENTRY_ZONE`"). Multiple strategies aligning beats a lone signal.
- **Extension** — % above the 21 / 50 EMA. ~3% above = reasonable; ~15-25%+ above = chasing.
- **Trend alignment** — above the 50 EMA *and* the 200 EMA (full alignment) vs only one vs neither.
- **Market regime** — is the tape supporting the trade? QQQ above its own 21 EMA, semis (SMH) above its 21 EMA, and the AI-basket breadth (from the scorecard). Sometimes the sector matters more than the stock.
- **Trade plan** —
  - **Stop**, chosen by setup type: EMA pullback → just below the 21 EMA; consolidation → below the range low; ATH dip → below the recent swing low.
  - **Invalidation condition** (plain text): "close below the 21 EMA" / "breakdown from the base" / "loss of the 50 EMA".
  - **Targets**: nearest resistance / ATH / measured move, with R:R.
  - **Position plan — informational only, never automated:** a sizing *tier* tied to the grade (HIGH-QUALITY → full, DECENT → half, MARGINAL → starter), where you'd add, and profit-taking levels (e.g. +10% / +15% / trailing).
- **Catalyst check** — earnings proximity + recent headlines ("why is it pulling back?", Session 8), plus a **manual-check reminder** for catalysts with no free feed (product launch, investor day, lockup expiration, regulatory decision).

Example dossier:

```
NVDA ⭐⭐⭐   ENTRY_ZONE                       Grade: HIGH-QUALITY

Reasons to BUY                    Reasons NOT to buy
- Above 50 & 200 EMA             - Earnings in 4 days ⚠️
- ENTRY_ZONE + bullish engulfing - 18% above 50 EMA (extended)
- Outperforming QQQ & SMH        - Resistance only 2% overhead
- 2/4 strategies aligned
- AI breadth 29/38 bullish

Strongest bull: relative strength      Strongest bear: overhead resistance
Trade plan:  stop $205 (below 21 EMA) · invalidation: close < 21 EMA ·
             target $250 (+15.7%) · R:R 3.1 · size: FULL · take profits +10% / +15%
```

---

## Dashboard

**Overview page** — table of every ticker with:
- Current price, % change today
- Value chain layer tag (filterable)
- Active strategy signals (badges: EMA_PULLBACK / CONSOLIDATION / ATH_DIP / IPO_BASE)
- Confidence stars (⭐–⭐⭐⭐) based on bullish pattern confirmation
- Distance to 9 EMA, 21 EMA (as %)
- Distance to ATH (as %)
- Consolidation status (days in range, range width)
- Bullish pattern detected (if any, e.g., "Hammer" / "Engulfing")
- Sortable by "closest to entry" and by confidence score

**Chart page** — per-ticker candlestick with:
- 9 EMA, 21 EMA, 50 EMA overlaid
- ATH line
- Consolidation range shading (when applicable)
- Volume bars with average volume line
- Signal markers (dots/arrows where alerts fired historically)
- Bullish pattern annotations on candles where detected
- Last 90 days default, expandable

**Value chain view** — group tickers by layer, show which layers have the most active signals. "Layer 4 — Interconnects has 3 stocks approaching entry" type summary.

**Alerts page** — chronological log of fired alerts with:
- Which strategy triggered
- Confidence stars (⭐–⭐⭐⭐) and which bullish pattern confirmed (if any)
- Entry price level
- Ack/dismiss
- Filterable by strategy type, value chain layer, and minimum confidence

---

## Setup

```bash
# clone, then:
uv sync                                          # or: pip install -e .
cp .env.example .env                             # edit if needed
python -m src.agent &                            # background agent
streamlit run src/dashboard/app.py               # dashboard at localhost:8501
```

`pyproject.toml` uses `uv` (faster than pip). Fall back to `pip install -e .` if `uv` not installed.

---

## Conventions

- **Type hints everywhere** — `mypy --strict` should pass
- **No bare except** — catch specific exceptions, log with context
- **All times in UTC internally** — convert to local only at display
- **Market hours awareness** — agent doesn't hammer yfinance on weekends/after close
- **One-shot CLI for testing** — `python -m src.agent --once` runs a single eval cycle without scheduling, useful for debugging
- **Config via env or YAML** — never hardcode tickers, thresholds, or paths in modules
- **Tests per session** — each implementation session adds tests for the code it introduces. Full suite must pass before moving to the next session
- **Strategy interface** — all strategies implement the same `base.Strategy` abstract class so the orchestrator treats them uniformly

---

## Out of scope (for v1)

- Brokerage integration / automated order placement
- Intraday timeframes (4h, 1h) — daily only (a higher **weekly** timeframe for trend alignment is added in Session 12; 4h/1h intraday stays out)
- Full backtesting framework (a *lightweight* per-setup win-rate replay is now in Session 8; a full strategy backtester/optimizer stays out)
- Options flow / unusual options activity
- News sentiment / NLP on earnings calls
- Relative strength ranking system → **now Session 11** (cross-sectional percentile rank + opportunity ordering)
- Automated position sizing / risk management (Session 9 adds *informational* sizing tiers, stop/target, and profit-take levels; Session 11 adds suggested allocation % — all suggestions, never auto-executed; actual order placement stays out; **paper-portfolio exposure / conviction sizing / RS rotation = Session 13 (validated in Session 14); real-holdings exits = v2 track**)
- Sector rotation quantitative model → **now Session 11** (numeric layer strength + rotation Δ; was qualitative-only)

These are good v2 candidates but would balloon scope.

---

## Open questions

Tagged by priority. **Resolve 🔴 before writing code.** Update this section as decisions get made.

### 🔴 Must answer before coding (architecture-affecting) — ✅ RESOLVED 2026-05-29

1. **Where does the agent run?** → **This laptop (Windows 11).** Scheduler is designed for "run once after market close + manual `--once`"; missed cycles need no backfill since only the latest daily close matters.
2. **Data source strategy.** → **(a) yfinance only.** `data.py` exposes a single `fetch_prices()` seam so an Alpha Vantage/Polygon fallback can be added later without touching callers.
3. **Evaluation cadence.** → **Daily-close only.** One end-of-day evaluation on US trading weekdays. No 30-min intraday loop. This simplifies Session 4's scheduler.
4. **Dashboard access.** → **Localhost-only**, no auth/HTTPS.

### 🟡 Should answer for v1 (feature-affecting)

5. **Trend filter.** Should the agent skip alerts when the stock is in a downtrend? Proposed rule: only alert if price > 50 EMA. Otherwise EMA touches in a falling stock generate constant noise.
6. **Volume confirmation.** Require above-average volume on the EMA touch for a higher-quality signal, or alert on any touch regardless of volume?
7. **Alert channels.** Desktop notifications (default), email, Discord webhook, Slack webhook, SMS (Twilio)? Pick any combination.
8. **Stop-loss in alert body.** → **Resolved (Session 7):** yes — the scorecard's risk/reward check computes entry / suggested stop / target and shows R:R in the composite alert.
9. **Watchlist edits.** YAML file the user edits manually, or a "manage tickers" page in the dashboard?
10. **Pre/post-market data.** Include extended hours in price/EMA calc, or regular session only?
11. **Consolidation parameters.** Strategy 2 defaults: 8% range, 10+ trading days. Are these reasonable for AI stocks, or should the range be wider (these are volatile names)?
12. **ATH pullback thresholds.** Strategy 3 defaults: entry zone = 5–10% below ATH. Should this vary by stock type? (e.g., volatile small caps like RDW might need 10–15%, while NVDA entry at 5–7% is already significant)
13. **IPO tracking.** When Anthropic/OpenAI IPO dates are announced, how should the agent pick up the ticker? Manual add to YAML, or auto-detect from a news scan?
14. **Strategy weighting/priority.** Should the dashboard rank strategies equally, or weight some higher? (e.g., IPO base breakout on ANTH > EMA pullback on SIEGY)
15. **Pattern library.** Start with the 6 candlestick patterns listed, or include more? `pandas-ta` supports ~60 patterns — too many creates noise. Which additional patterns (if any) are worth including?
16. **Confidence threshold for alerts.** Should ⭐ signals still fire desktop notifications, or only ⭐⭐+? Lower threshold = more alerts but more noise.

*(Session 13/14 questions — numbered 27–29 to avoid clashing with the 🟢 items 17–26 below.)*

27. **Exposure floor in RISK_OFF.** Default 30% invested. Go fully to cash (0%) for maximum defense, or keep a floor to avoid missing sharp recoveries? Backtest both in Session 14.
28. **Concentration vs. smoothness.** `max_positions` 6 and `max_position_pct` 25% is aggressive. More positions / lower caps = smoother, closer to the index. Tune against the Session 14 Sharpe.
29. **Rebalance cadence.** Weekly default. Daily churns/costs more; monthly is calmer but slower to cut losers. Let the backtest's turnover/cost drag decide.

### 🟢 Nice-to-have (defer to v2 unless requested)

17. **Trade journal.** Let user mark "I bought this alert at $X" and track outcomes. → **Part of the deferred v2 portfolio-aware track** (needs a holdings input; see after Session 12).
18. **Historical signal viewer.** → **Scheduled (Session 8):** a lightweight per-setup historical replay computes the forward 5/10/20-day win rate for each (ticker, strategy, status). Not a full backtester — just base rates for the scorecard's "historical edge" check.
19. **International tickers.** yfinance supports SIE.DE, 6981.T, etc. Include non-ADR foreign tickers?
20. **Multi-timeframe.** 4h and 1h EMAs alongside daily. → **Weekly** trend alignment is now Session 12; 4h/1h intraday stays a v2 candidate.
21. **News/catalyst tagging.** → **Scheduled (Session 8):** recent headlines via yfinance + an earnings-beat heuristic feed the scorecard's "catalysts" check. Earnings proximity is its own check (Session 7). No NLP/sentiment.
22. **Relative strength overlay.** → **Scheduled (Session 7):** relative strength vs SPY / QQQ / SMH is a scorecard check; the dashboard can surface the strongest names.
23. **IPO news scanner.** Auto-detect Anthropic/OpenAI IPO filings (S-1, pricing) from news feeds and auto-add tickers.
24. **Value chain flow alerts.** "3 out of 5 interconnect stocks are consolidating" — layer-level signal aggregation. → **Scheduled (Session 11)** via layer-strength scoring.
25. **Sector rotation detection.** When money moves between value chain layers (e.g., from semis to power), flag the shift. → **Scheduled (Session 11)** via layer-rotation Δ.
26. **Chart pattern detection (multi-week).** Double bottom, inverse head and shoulders, cup and handle — heavier computation but higher conviction signals.

### Assumptions made silently (override anytime)

These were chosen as defaults to make the spec concrete. Flag any you want changed:

- Watchlist as listed in the Watchlist section above (~40 tickers across 10 layers)
- All four strategies active for all tickers by default (strategies self-select based on stock state)
- Desktop notifications + dashboard for alerts (no email/webhook yet)
- Daily-close-only cadence: one evaluation after US market close on trading weekdays (resolved — was 30-min refresh)
- ~200 bars of daily history per ticker
- US-listed tickers only (ADRs for foreign names)
- No trend filter (alerts fire on any EMA touch, even in downtrends) — but see Q5
- No volume confirmation for Strategy 1 (EMA pullback); volume required for Strategy 2 (breakout) and Strategy 4 (IPO base)
- Bullish pattern confirmation active for all signals; 6 candlestick patterns (engulfing, hammer, morning star, three white soldiers, doji at support, piercing line)
- All confidence levels (⭐–⭐⭐⭐) fire alerts; no minimum threshold filter yet
- Localhost-only dashboard, no auth
- SQLite local file, no backup strategy
- Consolidation range: 8%, minimum 10 trading days
- ATH entry zone: 5–10% pullback
- IPO base strategy dormant until an IPO ticker is manually added
- Index-beating edge = dynamic exposure (regime dial) + conviction concentration + RS rotation, NOT entry precision. Drawdown avoidance is the primary alpha source. (Session 13)
- Paper portfolio only; rebalance suggestions never auto-execute
- Regime dial uses 3-day hysteresis to avoid whipsaw (mandatory guard)
- Top 6 names, 25% max single position, weekly rebalance, 3% no-trade band, 30% RISK_OFF floor
- No conclusion about beating VOO is valid until the Session 14 walk-forward backtest (net of costs, through a real drawdown). Build 13, then 14, before trusting a dollar
