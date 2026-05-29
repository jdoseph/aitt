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

**This project is built across 6 sequential sessions** defined in the "Implementation sessions" section. Each session is scoped and self-contained. At the start of each session:

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

Build this project across **6 sequential sessions**. Each session is self-contained — complete it fully, verify it works, then move to the next. Do not skip ahead. At the start of each session, **re-read this CLAUDE.md** and check if any open questions were resolved since last session.

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
- Intraday timeframes (4h, 1h) — daily only first
- Full backtesting framework (historical signal viewer is a lighter v2 option)
- Options flow / unusual options activity
- News sentiment / NLP on earnings calls
- Relative strength ranking system (v2 candidate)
- Automated position sizing / risk management
- Sector rotation quantitative model (qualitative in v1 via value chain view)

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
8. **Stop-loss in alert body.** Include suggested stop (e.g., "9 EMA at $19.50, suggested stop $18.30 / -6%") or keep alerts minimal?
9. **Watchlist edits.** YAML file the user edits manually, or a "manage tickers" page in the dashboard?
10. **Pre/post-market data.** Include extended hours in price/EMA calc, or regular session only?
11. **Consolidation parameters.** Strategy 2 defaults: 8% range, 10+ trading days. Are these reasonable for AI stocks, or should the range be wider (these are volatile names)?
12. **ATH pullback thresholds.** Strategy 3 defaults: entry zone = 5–10% below ATH. Should this vary by stock type? (e.g., volatile small caps like RDW might need 10–15%, while NVDA entry at 5–7% is already significant)
13. **IPO tracking.** When Anthropic/OpenAI IPO dates are announced, how should the agent pick up the ticker? Manual add to YAML, or auto-detect from a news scan?
14. **Strategy weighting/priority.** Should the dashboard rank strategies equally, or weight some higher? (e.g., IPO base breakout on ANTH > EMA pullback on SIEGY)
15. **Pattern library.** Start with the 6 candlestick patterns listed, or include more? `pandas-ta` supports ~60 patterns — too many creates noise. Which additional patterns (if any) are worth including?
16. **Confidence threshold for alerts.** Should ⭐ signals still fire desktop notifications, or only ⭐⭐+? Lower threshold = more alerts but more noise.

### 🟢 Nice-to-have (defer to v2 unless requested)

17. **Trade journal.** Let user mark "I bought this alert at $X" and track outcomes.
18. **Historical signal viewer.** "Show me every time RDW touched its 21 EMA in the last 12 months" with the subsequent 5/10/20-day return. Useful for confidence without building a full backtester.
19. **International tickers.** yfinance supports SIE.DE, 6981.T, etc. Include non-ADR foreign tickers?
20. **Multi-timeframe.** 4h and 1h EMAs alongside daily.
21. **News/catalyst tagging.** Annotate alerts with whether earnings is within 7 days, etc.
22. **Relative strength overlay.** Track each ticker's performance vs. SPY or QQQ — highlight names with strongest relative strength.
23. **IPO news scanner.** Auto-detect Anthropic/OpenAI IPO filings (S-1, pricing) from news feeds and auto-add tickers.
24. **Value chain flow alerts.** "3 out of 5 interconnect stocks are consolidating" — layer-level signal aggregation.
25. **Sector rotation detection.** When money moves between value chain layers (e.g., from semis to power), flag the shift.
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
