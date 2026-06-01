# Session 16 — Options Expression Layer (design)

**Date:** 2026-05-31
**Status:** approved (brainstorm), pending spec review
**Branch target:** new feature branch off `session-15-paper-trading` (or `main` once S15 merges)

## Goal

Let the existing four strategies be traded as **options** instead of only shares,
without changing how signals are generated. A bullish signal on the underlying is
*expressed* as a long call; everything downstream of that expression — strike/expiry
selection, sizing, pricing, exits, the paper book, and the backtest — is new and
options-aware. All paper-only; never routed to a broker.

## Key decisions (from brainstorming)

| Decision | Choice | Consequence |
|---|---|---|
| Scope | **Options layer on top** | Sessions 1–15 unchanged; signals stay on the underlying. |
| Pricing | **Hybrid** | Live chain at *entry* when available; Black-Scholes for *all* marks + the entire backtest. |
| Structure | **Long calls only** | Single leg; defined risk = premium; spreads deferred. |
| Strike/expiry | **Target delta + target DTE** | Strike ≈ 0.60 Δ, expiry ≈ 45 DTE; auto-adapts per name's vol. |
| IV source | **Live IV, realized-vol fallback** | Live ATM IV at entry when available; RV proxy otherwise and in backtest. |
| Exits | **Both, whichever-first** | Underlying stop/target OR premium ±% OR DTE/expiry. |
| Coexistence | **Run alongside, config toggle** | Stock paper book (S15) kept; `trade_instrument` selects stock/option/both. |
| Universe | **Trade all, model anyway** | BS prices any name; illiquid names flagged in the dashboard disclaimer. |

## The reconciliation rule (stated once)

*Entry* may use the live option chain (real mid + real ATM IV). **Every subsequent
valuation and the entire backtest use Black-Scholes + realized-vol.** The only place
live and model prices meet is the single entry fill, tagged `price_source` on the
trade. This keeps marks/P&L deterministic and prevents a position from becoming
unpriceable when a live quote disappears.

## Honest caveats (baked into the dashboard disclaimer)

- BS marks ≠ real fills; the model ignores IV smile/skew and term structure.
- IV-crush around earnings is **not** modeled when using the RV proxy.
- "Trade all, model anyway" means illiquid names (RDW, LUNR, ASTS, ABBNY, IFNNY,
  RNESY, SIEGY) show modeled fills with **no real options market behind them** —
  their results overstate realism and are flagged as `price_source=model`.
- Estimated slippage, ~15-min delayed underlying data, no partial fills, no
  assignment/early-exercise nuance (long calls only mitigates this), no tax drag.

## Architecture

Options layer sits on top of the unchanged pipeline
(strategies → scorecard → dossier → regime gate → composite/ranking). New modules:

```
src/core/options/
├── pricing.py       # bs_price, bs_greeks (delta/theta/vega/gamma), implied_vol solver — pure
├── vol.py           # realized_vol(df, window) -> annualized sigma
├── chain.py         # fetch_chain(ticker, expiry) via yfinance; thin/empty -> None (injectable)
├── contracts.py     # OptionContract model; select_contract(target_delta, target_dte)
└── option_trades.py # OptionBook: PENDING->OPEN->CLOSED, greeks-aware sizing, NAV/P&L
```

Reused unchanged: `signals.py`, `dossier.py`, `regime.py`, `ranking.py`, `scoring.py`,
scheduler, notify, storage facade pattern, Session 14 backtest harness (extended, not rewritten).

### Module responsibilities

- **pricing.py** — pure functions, no I/O. `bs_price(S,K,T,r,sigma,call=True)`,
  `bs_greeks(...)`, `implied_vol(price,S,K,T,r,call=True)` (Newton with bisection
  fallback). Unit-tested against known values + put-call parity + IV round-trip.
- **vol.py** — `realized_vol(df, window=20)` → annualized stdev of daily log returns,
  × `option_iv_premium_mult`. Sole IV source in the backtest; fallback live.
- **chain.py** — only network piece. `fetch_chain(ticker, expiry)` → parsed calls/puts
  (strike, bid, ask, IV, open_interest); returns `None` when empty/thin. Injected as a
  provider so tests stay offline (mirrors benchmark/earnings providers).
- **contracts.py** — `OptionContract` (type, strike, expiry, dte, iv, delta, source);
  `select_contract(underlying_df, chain_or_none, target_delta, target_dte)` → expiry
  nearest target DTE, then strike nearest target delta (live chain deltas if present,
  else BS deltas off the RV proxy).
- **option_trades.py** — `OptionBook`, the options analogue of S15 `PaperBook`. Positions
  are contracts (×100 multiplier). Hybrid pricing. Sizing by premium against the budget.

## Data flow

### Entry (daily-close queue → next-open fill)
1. Signal qualifies exactly as Session 15 (composite ≥ `paper_min_score`, grade ≥
   `paper_min_grade`, regime ≠ RISK_OFF, not already held).
2. `select_contract` picks expiry (nearest `option_target_dte`, default 45) and strike
   (nearest `option_target_delta`, default 0.60).
3. IV = live ATM IV (chain) if usable, else `vol.realized_vol`.
4. Entry premium (hybrid) = live mid `(bid+ask)/2` if present, else `bs_price`. Apply
   options slippage (half-spread when live; `option_slippage_bps_model` when modeled).
   Record `price_source` (`chain`|`model`).
5. Size: `contracts = floor(planned_dollars / (premium × 100))`, clamped so cost ≤
   `max_position_pct × budget`, ≥ 1 contract (skip if one contract exceeds the cap).
   Snapshot decision + contract immutably.

### Daily mark + monitor
Every open position is **marked with Black-Scholes** off that day's underlying close +
current RV (consistent, reproducible, independent of a possibly-vanished live quote).
Greeks recomputed for display.

### Exit (whichever-first)
Close when **any** trips:
- underlying ≤ dossier stop
- underlying ≥ dossier target
- option premium ≥ `+option_tp_pct`
- option premium ≤ `−option_sl_pct`
- `DTE ≤ option_min_dte_exit` (default 21) — theta/gamma cliff guard
- expiry (settles at intrinsic value)

Exit premium uses the same hybrid rule.

## Storage (two new tables, mirroring S15)

- **`option_trades`** — S15 `paper_trades` fields plus: `option_type`, `strike`,
  `expiry`, `dte_at_entry`, `contracts`, `multiplier` (100), `entry_iv`, `entry_delta`,
  `price_source`, `underlying_entry`, `underlying_stop`, `underlying_target`,
  `tp_pct`, `sl_pct`, greeks snapshot. P&L = `(exit_premium − entry_premium) ×
  contracts × 100`.
- **`option_cashbook`** — daily NAV vs VOO for the options book.

CRUD + lifecycle methods on the `Storage` facade, same shape as the S15 helpers.

## Config (`# --- Session 16: options layer ---`)

`trade_instrument` (`"stock"|"option"|"both"`, default `"both"`), `enable_options`
(True), `option_target_delta` (0.60), `option_target_dte` (45),
`option_min_dte_exit` (21), `option_tp_pct` (50.0), `option_sl_pct` (50.0),
`option_structure` (`"long_call"`), `risk_free_rate` (0.04),
`option_iv_premium_mult` (1.1), `realized_vol_window` (20),
`option_slippage_bps_model` (50.0), `option_chain_min_oi` (used only to decide if a
live chain is "usable", **not** a trade gate).

## Scheduler / jobs

The existing three paper jobs (9:31 fill, */5-min monitor, 16:30 summary) branch on
`trade_instrument`: when `option`/`both`, they also run the analogous
`execute_market_open` / `monitor_positions` / queueing against the `OptionBook`. Same
holiday guard, same windows, same `enable_*` gating.

## Backtest (extend Session 14)

Same no-lookahead walk-forward replay; each position is a **BS-priced call** (RV-based
IV), marked daily, exited by the whichever-first rules. Reports the options book vs VOO
net of modeled options slippage. The "BS-only, reproducible" choice is what makes this
possible.

## Dashboard

New **Options** page parallel to Paper Trades: NAV-vs-VOO equity curve; open positions
(strike/expiry/DTE/Δ/premium/underlying-vs-stop-target); closed trades (P&L + exit
reason); decision snapshots; win-rate breakdown; disclaimer flagging model-priced
(illiquid) names.

## Testing (TDD)

- `test_pricing.py` — BS price/greeks vs known values, put-call parity, IV solver round-trip.
- `test_vol.py` — realized-vol on synthetic series.
- `test_contracts.py` — delta/DTE selection on synthetic chains + model fallback.
- `test_option_trades.py` — lifecycle, ×100 P&L, greeks-aware sizing, budget cap.
- `test_option_monitor.py` — each of the 6 exits + expiry settlement.
- `test_option_chain.py` — mocked yfinance; thin/empty → None fallback.
- storage + dashboard-helper tests.
- `mypy --strict` clean throughout.

## Out of scope (this session)

Multi-leg structures (spreads, straddles), puts / bearish expressions, early-exercise /
assignment modeling, IV smile/skew/term-structure, live order routing, the Claude-API
trade-autopsy learning loop (still deferred).
