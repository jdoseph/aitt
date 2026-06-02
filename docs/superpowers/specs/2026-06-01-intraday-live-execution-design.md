# Intraday-Signal + Broker-Confirmation Live Execution (design spike)

**Date:** 2026-06-01
**Status:** design spike — **saved for the future, NOT scheduled for implementation.** No plan, no code yet.
**Branch target:** a future feature branch off `main` (after Sessions 15–16 merge).

> **Read this first.** Everything in Sessions 1–16 is **paper-only by design** and the strategy
> is **unvalidated through a real drawdown** (the Session 14 backtest hasn't been run on real
> history yet). This document describes how the agent *could* place **real money** orders someday.
> It is deliberately conservative, human-in-the-loop, and phased. Do not implement any live-money
> phase until (a) the Session 14 walk-forward backtest has run through a real drawdown, and (b) the
> paper books (stock + options) have been observed live through one. The tool can be built; the
> decision to route real orders is data-dependent and reversible only at a cost.

## Goal

Add an **opt-in, flag-gated** live-execution path that generates **entry signals during market
hours** and, on your **explicit per-trade approval**, routes a **real Schwab order** that fills
**same-day**. The existing paper engine (stock + options) keeps running untouched in parallel as
the control. This is purely additive: nothing in the daily-close paper pipeline changes.

### What changes vs. today

| | Today (Sessions 15–16) | This spike |
|---|---|---|
| Entry signal timing | daily close (~16:15 ET) | **intraday**, via precomputed levels |
| Fill | next day's open | **same day**, on a live cross + approval |
| Money | simulated (paper books) | **real** (Schwab), behind a kill switch |
| Human in loop | none (autonomous paper) | **per-trade approve/reject** (time-boxed) |
| Quote feed | yfinance (~15-min delayed) | **Schwab real-time stream** |

## Key decisions (from brainstorming, 2026-06-01)

| Decision | Choice | Consequence |
|---|---|---|
| Confirmation model | **Push-notify + approve/reject, time-boxed** (via **Telegram** bot buttons; email as redundant notify) | No order routes without your tap; stale setups auto-expire; free + no exposed ports. |
| Intraday trigger | **Armed trigger levels** | Precompute the level from the *closed* daily bar; intraday only test price-vs-level. Sidesteps the unfinished-candle problem. |
| Broker boundary | **`BrokerClient` protocol → Schwabdev adapter (default)** | In-process Python; **no MCP, no Cloudflare, no Durable Objects**. schwab-py / local MCP are drop-in alternatives; hosted MCP is out of scope. |
| Quote feed | **Schwabdev WebSocket streamer** (push, auto-recovery) | Callback-driven trigger detection; reconnects itself on the always-on laptop. |
| Protective exits | **Broker-resident GTC/OCO stop on every fill** | Laptop death never leaves a position unprotected. |
| Deployment | **Always-on local laptop** | You are the host; nothing in the cloud is needed. |

### Why not the hosted Cloudflare MCP

The `sudowealth/schwab-mcp` server requires Cloudflare Workers **Paid** (Durable Objects) because
it is a **remote, multi-user, hosted** MCP — Durable Objects hold OAuth + per-connection session
state at the edge. That architecture serves *remote* clients; it is overkill for a single-user
local agent. Crucially, hosting *only the MCP* in the cloud would **not** let the agent trade while
the laptop is off: the MCP is just the broker's hands — the **brain** (arming, trigger-watching,
sizing, the decision pipeline) is the local Python agent. Trading while away would require hosting
the **entire agent** on an always-on cloud VM (a much larger, riskier deployment, explicitly out of
scope). Therefore: **leave the laptop on; use an in-process broker adapter; need nothing in the cloud.**

## The "armed levels" model

Two phases. The first reuses the existing daily-close machinery; the second is the new intraday loop.

> **Framing — evaluation stays at the close; only *entry timing* moves intraday.** This model does
> NOT re-run the strategies on live intraday data. The whole "is this a good setup?" judgment —
> which of the four strategies fired, the scorecard grade, regime gate, composite score, sizing, and
> *which price level to arm* — is computed at the **daily close from the completed prior bar**,
> exactly as today. The intraday loop only **watches for price to reach a level that was already
> deemed good at the close.** So the one-line difference from today is: *same four strategies,
> evaluated end-of-day, with intraday entry timing instead of next-open entry.* It is **not** fresh
> intraday analysis (that was the "periodic full re-eval" option, deliberately rejected for noise
> and the unfinished-candle problem).

### Phase A — Arm (at the daily close, piggybacks `daily_eval`)
For each gradeable, non-disqualified candidate from the normal pipeline, compute an **ArmSpec**:
- **trigger price** — the strategy's entry level derived from the *completed* prior daily bar:
  - EMA pullback (S1) → the 9/21-EMA touch price,
  - consolidation breakout (S2) → the range-high breakout price,
  - ATH pullback (S3) → the entry-zone price,
  - IPO base (S4) → the IPO-high breakout price (dormant until a recent-IPO ticker is on the
    watchlist — included for parity with the four-strategy engine),
- **direction** of the cross (e.g. cross **down** to a pullback level, cross **up** through a breakout),
- **side** (long-only in v1, matching the paper engine),
- the full **decision snapshot** (composite, grade, dossier, stop, target) — frozen immutably,
- **size** (reuse the existing sizing: conviction × budget, concentration cap),
- **expiry** — valid for the **next session only** (re-armed each close).

Persist as `ARMED` rows. (Levels are precomputed from a *closed* bar, so they're stable all session.)

**Two conditions don't reduce to a pure price level — handle them at arming time:**
- **Volume confirmation (S2, S4).** Breakouts require >1.5× average volume, which a price-cross alone
  can't verify. The watch loop checks **live cumulative session volume vs. the 20-day average** at
  the moment of the cross, and the approval card surfaces the live volume ratio so you can judge a
  thin breakout. (A cross on weak volume can be set to auto-expire rather than notify.)
- **Candlestick pattern confirmation.** A daily bullish-engulfing/hammer can't be confirmed until the
  bar *closes*, so it can't gate a live intraday entry. The arming step uses the **prior closed
  bar's** pattern (already in the snapshot) as context; the live path does not wait for an intraday
  pattern. This means a live fill may carry slightly less pattern confirmation than the next-open
  paper fill would — an accepted tradeoff of acting intraday.

### Phase B — Watch (intraday, push-based via the Schwabdev streamer)
- Subscribe the **WebSocket streamer** to all armed tickers (LEVELONE equities).
- Trigger detection runs **in the stream callback**: on each price update, test live price against
  the armed level in the armed direction. On a cross → `ARMED → TRIGGERED`.
- The streamer's **auto-recovery** reconnects a dropped socket; **market-driven start/stop**
  subscribes at the open and tears down at the close.

> Real-time quotes are mandatory here. yfinance's ~15-min delay is disqualifying for live triggers;
> yfinance remains only for historical/daily indicator computation.

## Confirmation loop (human-in-the-loop, time-boxed)

State machine:

```
ARMED → TRIGGERED → { APPROVED | REJECTED | EXPIRED }
                          │
                     APPROVED → SUBMITTED → { FILLED | PARTIAL | CANCELED }
```

- On `TRIGGERED`, push a notification containing: ticker, side, trigger vs live price, suggested
  **limit** price, size ($ + shares), stop/target, grade/score, strongest bull + strongest bear
  reason, and **Approve / Reject** action buttons.
- **Channel:** decided **Telegram bot inline buttons for the action + email as a redundant
  notification** (see the full option comparison below). All channels sit behind one
  `ConfirmChannel` interface (`send(request) -> awaits APPROVE | REJECT | EXPIRE`), so the choice is
  swappable and more than one can run at once.
- **Config:** `confirm_channel` (which one is active), `telegram_bot_token` / `telegram_chat_id`,
  optional `email_smtp_*`. The bot only acts on taps from the configured `telegram_chat_id` (ignore
  anyone else who messages it).

### Confirmation channel options (full comparison)

"No exposed ports" = the agent reaches **out** to the service (long-poll / WebSocket / outbound
poll), so your laptop never has to accept inbound connections or run a tunnel. That property is what
lets you approve from anywhere (e.g. at work) without exposing your machine.

| Channel | Free | Approve/Reject buttons | No exposed ports | Setup | Best for / main tradeoff |
|---|---|---|---|---|---|
| **Telegram bot** ⭐ | ✅ | ✅ inline buttons | ✅ long-poll `getUpdates` | ~2 min (@BotFather) | **Default.** Free, instant, no ports, simplest. Trades pass through Telegram's servers (short alert text). |
| **Discord bot** | ✅ | ✅ message components | ✅ gateway WebSocket | ~10 min (app + a personal server) | Equal to Telegram if you already use Discord; needs a shared server for the bot to DM you. |
| **ntfy** | ✅ (self-hostable) | ✅ action buttons | ✅ via a response topic the agent subscribes to | moderate | Most private (self-host the server); open-source. A bit more wiring for the button round-trip. |
| **Pushover** | ❌ $5 one-time/platform | ⚠️ ack-only (emergency priority) | ✅ poll the receipt API (outbound) | moderate | "Acknowledge = approve, expire = reject" — one-tap, cheap, but not two distinct buttons and not free. |
| **Email — action links** | ✅ | ⚠️ links, not buttons | ❌ links must reach the agent → **tunnel** | low + tunnel | Familiar, but needs a tunnel and email latency eats the time-box. |
| **Email — reply APPROVE** | ✅ | ❌ reply text | ✅ agent polls IMAP (outbound) | low (app password) | Least new infrastructure (your existing inbox), but slowest + fragile reply-parsing. |
| **SMS (Twilio)** | ❌ ~$1–2/mo + per-msg | ❌ reply-only | ❌ inbound webhook | high | The only one needing **no app / works on weak data / any phone**; costs money + an endpoint. |
| **Desktop toast (`plyer`)** | ✅ | ❌ (click opens local UI) | ✅ local | none (already in project) | **Local fallback only** — works solely when you're at the laptop, so useless while at work. |
| **Dashboard queue (Streamlit)** | ✅ | ✅ in-page | ⚠️ localhost; remote needs a tunnel | low (reuse dashboard) | No push — you must be watching the dashboard. Fine at-desk, not for "away." |

⭐ = recommended default. **Email** is additionally used as a **redundant one-way notification**
regardless of which action channel is chosen, so there's always an inbox record. **Desktop toast**
and the **dashboard queue** are local fallbacks for when you're *at* the machine; everything above
SMS gives phone-native approval from anywhere with no exposed ports.
- **Time-box:** if not approved within `live_confirm_ttl_min` (~10–15 min) **or** price runs past
  `live_max_chase_pct` from the trigger → **EXPIRES**, no order. Missing a fast mover is *correct
  behavior*, not a bug.

## Order routing (Schwab via Schwabdev, behind a protocol seam)

- **`BrokerClient` protocol:** `quote`, `place_order`, `get_order`, `cancel_order`,
  `replace_order`, `get_positions`, `get_account`. Mockable offline for tests; broker-swappable.
- **Default impl:** a **Schwabdev** adapter (in-process Python, MIT). Alternatives noted but not
  built: a schwab-py adapter, or a *local* stdio MCP for credential isolation.
- **Order type:** **marketable-limit, DAY TIF — never a bare market order.** Limit = live mid (or
  trigger ± a small offset) to bound slippage. Client-supplied order IDs for **idempotency** (no
  double-submit on retry). Confirm the real fill by polling `get_order`, then reconcile into the
  local book.

## Protective exits (mandatory safety rule)

When a live entry **fills**, immediately submit a **broker-resident GTC stop (or OCO stop+target)**
order to Schwab for that position. Schwab then enforces the exit **even if the laptop sleeps,
loses Wi-Fi, reboots, or dies.** The agent's intraday monitor becomes a *second* layer (active /
trailing management), never the *only* layer protecting a position. This single rule converts "my
laptop is a single point of failure for my downside" into "laptop downtime only stops *new* entries
and active management — my risk is still capped by a real broker stop."

## Safety rails (real money — all mandatory)

- **Global kill switch** (env flag + dashboard button) halts all routing instantly.
- Per-order $ cap; per-name cap (reuse `max_position_pct`); daily new-capital cap; max concurrent
  live positions.
- **Daily loss limit / drawdown circuit breaker** → disarms everything for the rest of the day.
- **Broker is the source of truth:** reconcile real positions/orders against the local book on
  startup and every cycle — handles partial fills, rejects, *and trades you place manually*.
- **PDT guard:** under $25k account equity, brokers cap day-trades at 3 per rolling 5 days. The
  agent must **count day-trades and refuse** to arm/route past the limit (same-day entry+exit is a
  day-trade).
- Trading-day / market-hours guard (reuse `is_trading_day`); duplicate guard (never arm/route a
  name already held or pending live); immutable decision-snapshot logging (extends the existing
  snapshot pattern).

## Architecture (additive; reuses the existing brain)

New package `src/core/live/`:
- `arming.py` — `ArmSpec` + `compute_arms(candidates)` from the daily-close pipeline.
- `triggers.py` — pure cross-detection (price vs. armed level + direction).
- `broker.py` — `BrokerClient` protocol + `SchwabdevBroker` impl + `MockBroker` for tests.
- `confirm.py` — confirmation-request lifecycle + TTL / max-chase expiry.
- `live_book.py` — LIVE order lifecycle, fills, P&L, **reconciliation against the broker**.

New agent piece:
- `src/agent/approval_server.py` — FastAPI approve/reject endpoint + kill-switch control.

Reused **unchanged:** `signals`, `scorecard`, `dossier`, `regime`, `sizing`, `is_trading_day`;
`notify` (extended with a push channel); `scheduler` (a pre-open arming job + the intraday
streamer/watch job); `execution` slippage concepts (for limit offsets).

### Storage (new tables, mirroring the paper pattern)
- `live_arms` — armed level, direction, side, snapshot JSON, size, expiry, state.
- `live_orders` — broker order id, status, fills, prices, stop/OCO ids, P&L, snapshot JSON.

### Config (`# --- live execution ---`)
`enable_live_trading` (default **False**, hard-off), `live_confirm_ttl_min`, `live_max_chase_pct`,
`live_order_type` (`marketable_limit`), `live_daily_loss_limit`, `live_per_order_cap`,
`live_max_concurrent`, `live_watch_*` (stream config), `live_pdt_guard` (True), kill-switch flag,
push-channel credentials. Reuses `max_position_pct`, `paper_budget`-style sizing knobs.

## Data flow (timeline)

```
16:15 ET (close)   daily_eval runs as today  ──►  also writes ARMED rows for tomorrow
09:30 ET (open)    Schwabdev streamer subscribes armed tickers
intraday           price update ─► callback tests vs armed level ─► CROSS ─► TRIGGERED ─► push notify
you (phone)        Approve  ─►  FastAPI endpoint  ─►  broker.place_order (marketable-limit, idempotent)
fill confirmed     poll get_order ─► FILLED ─► live_book records ─► submit GTC/OCO protective stop ─► notify "✅ FILLED"
intraday monitor   manages live positions (active/trailing); broker stop is the hard floor
16:00 ET (close)   streamer tears down; reconcile vs broker; re-arm at 16:15 for the next session
```

Exits: extend the existing intraday monitor to manage live positions too. Exits are risk-reducing,
so they **may** be allowed to auto-route (a design choice to settle at implementation), but the
**broker-resident protective stop is always present regardless.**

## Deployment model (always-on local laptop)

- Disable sleep/hibernate during market hours; closing the lid must not suspend.
- Auto-reconnect (streamer handles its own; the agent reconnects the REST client) and
  **reconcile against the broker on every startup** so a mid-session crash recovers cleanly.
- **Heartbeat / dead-man alert:** if the agent goes silent during market hours, push an alert so you
  know active management is down (the broker stop still protects you).

## Phased rollout (de-risking — the core discipline)

- **Phase 0 — Shadow:** run arming + trigger + confirm end-to-end but route to the **paper** book.
  Validate intraday triggers and notifications. No real money, no Schwab.
- **Phase 1 — Read-only broker:** connect Schwabdev for **quotes + positions only**; validate
  OAuth, real-time stream, and reconciliation. No `place_order`.
- **Phase 2 — Live, confirmed, tiny caps:** enable `place_order` behind the kill switch with a small
  per-order cap and daily loss limit, plus broker-resident protective stops. Real money, small.
- **Phase 3 — Loosen caps** only after evidence — and only after the Session 14 backtest and a real
  paper-drawdown have actually happened.

## Honest risks / open questions

- **Strategy still unvalidated** through a drawdown — live money is premature until Session 14 runs.
- **Schwabdev (and schwab-py) are unofficial** community wrappers; you still need a **Schwab
  developer app** (developer.schwab.com — key/secret + approved OAuth callback). That approval, not
  the library choice, is the real gating step (can take days).
- **Refresh token lives on the laptop** (encrypted-store option helps) — never sync it to a public
  repo or the cloud.
- **PDT / wash-sale / tax** friction on same-day entries + exits; the PDT guard is mandatory.
- **Partial fills, halts, mid-order disconnects** make reconciliation non-trivial — the broker is
  the source of truth.
- **Approval latency** means real misses by design (the max-chase guard + marketable-limit bound it).

## Out of scope (this spike)

Hosted/Cloudflare MCP; cloud-hosting the whole agent (trade-while-laptop-off); short/options live
routing (long-equity only in v1, matching the paper engine); fully autonomous live entries (always
confirmed in v1); multi-account; algorithmic order types beyond marketable-limit + GTC/OCO.

## Next step (when picked up later)

Run the **writing-plans** skill against this spec to produce a phased implementation plan, starting
with **Phase 0 (shadow)** — no real money until Phases are walked in order.
