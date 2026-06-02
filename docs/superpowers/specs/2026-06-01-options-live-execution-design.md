# Options Live Execution (design spike)

**Date:** 2026-06-01
**Status:** design spike — **saved for the future, NOT scheduled.** No plan, no code yet.
**Companion:** builds on [`2026-06-01-intraday-live-execution-design.md`](2026-06-01-intraday-live-execution-design.md)
(the equity-live spike). This doc only describes the **options-specific deltas** — the shared
skeleton (armed levels, push-confirmation, Schwabdev adapter, kill switch, reconciliation, phased
rollout, always-on-laptop deployment) is defined there and is NOT repeated.

> **Same hard guardrail as the equity spike, and then some.** Live options are *harder and riskier*
> than live shares (wide spreads, thin liquidity, IV/greeks, faster decay). Do not route a single
> real options order until the equity-live path has been run live and the Session 14 backtest +
> a real paper drawdown have happened. Long calls only — no assignment risk lands on you.

## Goal

Let the agent tell you **what option to buy** for an intraday-triggered setup and, on your explicit
approval, route a **real long-call order** to Schwab that fills same-day. The Session 16 paper
Options engine already decides *what to buy*; this spike is about doing it **live, intraday, with a
human confirm.**

## What's already solved (reused from Session 16, unchanged)

The "what option to buy" brain exists — `src/core/options/` produces it every day at the close:
- **Which setup / underlying** — the four strategies + scorecard/composite rank it.
- **Which exact contract** — `select_contract` picks a **long call, ~0.60 delta, ~45 DTE**, sized to
  whole contracts within the budget/concentration cap.
- **Exit rules** — `evaluate_exit`: whichever-first of underlying stop / underlying target /
  premium **+`option_tp_pct`** / premium **−`option_sl_pct`** / **DTE ≤ `option_min_dte_exit`** /
  expiry.

This spike does **not** change any of that. It changes only *where the price comes from* (live chain
vs. Black-Scholes model) and *that the order is real*.

## Options-specific decisions

| Decision | Choice | Why |
|---|---|---|
| Structure | **Long calls only** (matches Session 16) | Defined risk = premium; no assignment risk on you; no margin. |
| Arming | **Arm the UNDERLYING level** (same as equity) | Strategies live on the underlying; the option is just the expression. |
| Contract pick at trigger | **`select_contract` against the LIVE Schwab chain** (real strikes/IV/greeks) | The model picks a *theoretical* contract at the close; at the live trigger, re-pick against the real chain so strike/expiry/premium are tradeable. |
| Entry order | **Marketable-limit on the live chain mid**, DAY TIF | Options spreads are wide; never a bare market order on an option. |
| Protective stop | **Broker-resident stop on the UNDERLYING** (hard floor) + agent manages premium-based exits | A broker stop *on the option premium* false-triggers on spread noise; an underlying stop is stable and broker-enforced even if the laptop dies. |
| Liquidity gate | **Live OI / spread check — refuse to route thin options** | The paper book is "trade all, model anyway"; the LIVE path must NOT route into an untradeable contract (illiquid names like RDW/LUNR/ASTS get flagged, not filled). |

## Data flow (deltas from the equity timeline)

```
16:15 ET (close)   Session 16 daily_eval already picks the model contract; arm the UNDERLYING level
intraday cross     streamer fires on the underlying ─► TRIGGERED
                   ─► re-run select_contract against the LIVE Schwab chain (real OI/IV/greeks)
                   ─► liquidity gate: OI >= min and spread <= max?  no -> SKIP (notify "untradeable")
approval card      "Buy 2x NVDA $220 C 2026-07-17 @ ~$7.40 ($1,480), Δ0.60, IV 33%,
                    underlying stop $205, premium TP +50% / SL -50%, DTE 46"   [Approve] [Reject]
you approve        ─► broker.place_option_order (marketable-limit on the chain mid, idempotent)
fill confirmed     poll get_order ─► FILLED ─► live_book records ─► submit GTC stop on the UNDERLYING
intraday monitor   manages premium TP/SL + DTE/expiry exits; underlying broker stop is the hard floor
```

## Confirmation channels

The channel set is **identical to the equity spike** — see its *"Confirmation channel options (full
comparison)"* table (Telegram ⭐ / Discord / ntfy / Pushover / email-links / email-reply / SMS /
desktop toast / dashboard queue), with **Telegram** the default and **email** as a redundant
notification. The **only options-specific difference**: the approval card renders the **contract +
greeks** instead of a share count — e.g. *"Buy 2× NVDA $220 C 2026-07-17 @ ~$7.40 ($1,480), Δ0.60,
IV 33%, underlying stop $205, TP +50% / SL −50%, DTE 46."* Same `ConfirmChannel` interface, same
time-box (TTL + max-chase), same no-exposed-ports property.

## Architecture (deltas only)

Reuses the equity spike's `src/core/live/` skeleton. Differences:
- `broker.py` — the `BrokerClient` protocol gains **options methods**: `option_chain`,
  `place_option_order`, plus options-aware `get_order` / `cancel_order`. Schwabdev supports options
  orders and chains; the protocol stays broker-swappable.
- `arming.py` — unchanged (arms the underlying). The ArmSpec records that the *expression* is an
  option so the trigger handler knows to run contract selection.
- `confirm.py` — the approval card renders the **contract + greeks** instead of shares.
- `live_book.py` — option lifecycle + P&L = `(exit_premium − entry_premium) × contracts × 100`,
  reconciled against the broker; tracks the linked underlying protective-stop order id.
- Reuses Session 16 `options/contracts.select_contract`, `options/pricing` (for the model fallback
  if the live chain is momentarily unavailable), and `options/option_trades.evaluate_exit`.

### Storage
- `live_option_orders` — broker order id, contract (type/strike/expiry/contracts/multiplier),
  entry/exit premium, price_source (`chain`|`model`), underlying stop order id, greeks snapshot,
  P&L, decision snapshot JSON. (Parallels Session 16's `option_trades`, with broker ids.)

### Config (`# --- live options ---`)
`enable_live_options` (default **False**, hard-off), `live_option_min_oi`, `live_option_max_spread_pct`
(liquidity gate), `live_option_order_type` (`marketable_limit`), plus reuse of the Session 16 knobs
(`option_target_delta`, `option_target_dte`, `option_tp_pct`, `option_sl_pct`, `option_min_dte_exit`)
and all equity-spike safety rails (kill switch, daily loss limit, PDT guard, caps).

## Honest risks specific to options-live

- **Liquidity is the real gate.** Many watchlist names have thin or non-existent options markets.
  The live path must refuse them (the gate above), so the live options universe is *smaller* than
  the paper one — expect fewer live trades than the paper Options book shows.
- **Spread slippage** dwarfs equity slippage; marketable-limit on the mid bounds it but you'll still
  pay up. Real fills will lag the model marks the paper book reports.
- **IV / earnings crush** is real here (the paper book ignores it). Avoid opening through earnings —
  reuse the scorecard's earnings-proximity check as a live disqualifier.
- **DTE decay** makes the time-box and the DTE≤21 exit more important, not less.
- **PDT** applies; same-day open+close of an option is a day-trade.
- **No broker stop on the premium** (by design) — between agent monitor cycles, a fast adverse move
  is only floored by the *underlying* stop, not a premium stop. Accept and document.

## Out of scope (this spike)

Spreads / multi-leg, puts / bearish expressions, selling premium, rolling, early-exercise handling
(mitigated by long-calls-only), and the Session 14 options-mode backtest (still deferred from
Session 16). Fully autonomous live options (always confirmed in v1).

## Next step (when picked up later)

Run **writing-plans** against *both* live specs — but sequence them: implement and live-validate the
**equity** path first (it's simpler and safer), then this options path as a later track. Phase 0
(shadow → paper) applies here too: route option triggers to the Session 16 paper book before any
real options order.
