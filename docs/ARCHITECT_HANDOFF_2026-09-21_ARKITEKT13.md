# PriceGauger Architecture Handoff — Arkitekt 13 — 2026-09-21

This is the authoritative handoff for the next PriceGauger architect after the September 16–21 TradingDesk live-chart repair, AutoTrader signal-contract hardening, runtime watchdog, Price-first strategy work, generic TakeProfit wrapper, and parameterized strategy-family rollout.

Always refresh from current `main` before branching. The SHA below is the exact baseline at handoff creation, not a permanent pin.

---

## 1. Exact starting point

Repository: `oveaignerhaukenes-lgtm/PriceGauger`

Authoritative `main` at handoff creation:

`97561cdb32eaee5174fd3fb6d5105f26bac59ade`

Latest important merged PRs:

- **#415 — AutoTrader: parameterized strategy families with SIM/LIVE modes**
  - merge commit `c3bf6d9a12d433e15da90e0e2b91ce0ac68a762d`
- **#416 — TradingDesk: make the main chart own live candle formation**
  - merge commit `030ceaf3ae680b3acb0b4ca19d14abd663878503`
- **#417 — Tests: verify parameterized strategy families end to end**
  - merge commit `97561cdb32eaee5174fd3fb6d5105f26bac59ade`

PR #417 head `0b227866f75ab764eadeb1a93baca162901d74f1` passed full GitHub workflow **Tests #2574** successfully before merge.

At handoff creation all Railway production services report **SUCCESS** on the current deployment:
- `pricegauger-web`
- `PriceGauger-stream`
- `PriceGauger-worker`
- `Spring-Trade-Engine`
- Postgres

Open PR worth knowing about:
- **#405 — Strategy Lab: add normalized large-move escape comparator**
  - still open as **draft**
  - intentionally *not* the production fix for the MACD lag problem
  - treat as stale research unless explicitly revived; safe candidate for cleanup/closure after review

Do not start from the old `feature/strategy-families-v1` branch. The family architecture is already merged and verified on current `main`.

---

## 2. What PriceGauger is now

PriceGauger is no longer just a chart + experimental AutoTrader. The current architecture has four distinct layers that must remain separate:

1. **Market/data layer**
   - canonical 1m bars
   - Saxo price/chart streams
   - forming candle presentation state

2. **Strategy layer**
   - computes desired `LONG / SHORT / FLAT`
   - may run in SIM and/or LIVE
   - must not POST broker orders directly

3. **Position-management modifiers**
   - generic wrappers such as `X + TakeProfit`
   - may temporarily own effective FLAT authority
   - remain logically separate from the base strategy

4. **Execution layer**
   - reconciles desired state against exact Saxo exposure
   - hardened invariant:
     `desired direction -> CLOSE opposite exposure -> confirm Saxo FLAT -> OPEN desired side`
   - this lifecycle is authoritative; no strategy may bypass it

The user is actively using PriceGauger as an autonomous trading system, so preserve auditability and restart safety over clever shortcuts.

---

## 3. Strategy families are now the primary model

The flat strategy-key UI is now legacy/compatibility. The new user-facing abstraction is:

`family + parameters + run mode + modifiers`

Implemented in:

- `autotrader_strategy_family_v1.py`
- `tradingdesk_strategy_family_ui_v1.py`
- `autotrader_family_replay_v1.py`

Primary families:

### MACD(N)

Family:
`MACD`

Stable strategy key:
`family-macd-v1`

User-selectable timeframe:
- presets: `1, 2, 5, 10, 15, 30, 60` minutes
- custom integer: `1..240` minutes

LIVE runtime reads the persisted family config and feeds the chosen timeframe into the real execution clock in `autotrader_macd_timeframe_live_v1.py`.

Important contract:
- fully closed N-minute MACD 12/26/9 cross is the direction signal
- a confirmed cross must not be vetoed by an extra score/hysteresis layer

### Price + MACD(N)

Family:
`PRICE_MACD`

Stable strategy key:
`family-price-macd-v1`

Core:
- `autotrader_price_macd_v1.py`
- `autotrader_price_macd_live_v1.py`

Same timeframe options as MACD.

Semantic contract:
- **price owns direction first**
- MACD is fallback/confirmation when price is neutral
- bearish MACD must not force SHORT while price is clearly trending up
- a confirmed price downtrend may reverse before MACD crosses
- stale MACD state alone must not bootstrap a FLAT position

This ordering is explicitly regression-tested. Do not invert it.

### Price + Stoch

Family:
`PRICE_STOCH`

Stable strategy key:
`price-stoch-half-parade-v1`

Core:
- `autotrader_price_stoch_v1.py`
- `autotrader_price_stoch_live_v1.py`

Current v1 timeframe:
- **fixed 1m**
- the family UI explicitly says this

Semantics:
- price owns direction
- fast stochastic %K slope/angle is the scout
- stochastic can trigger a **half-parade to FLAT** when price stops confirming the current position
- stochastic alone may **not** reverse LONG <-> SHORT
- actual reversal requires price confirmation

The stochastic “angle” is mathematical slope-derived, not chart-pixel angle, so zoom/scaling cannot change its meaning.

---

## 4. SIM / LIVE / both

The family builder supports explicit activation modes:

- `SIM`
- `LIVE`
- both

Important safety rule:
**nothing changes merely because a selector changes. The user must press Apply.**

Relevant UI:
`tradingdesk_strategy_family_ui_v1.py`

SIM config:
- persisted per instrument
- table: `pg_v2_autotrader_strategy_family_sim_config`
- Strategy Lab consumes the same family/timeframe policy through `autotrader_family_replay_v1.py`

LIVE config:
- persisted per pilot
- table: `pg_v2_autotrader_strategy_family_config`

LIVE parameter changes:
- block if execution is `SUBMITTING / ORDER_ACCEPTED / UNCERTAIN`
- supersede only unstarted `PENDING / APPROVED` intents
- clear fast runtime state
- next strategy cycle bootstraps from actual Saxo exposure
- do **not** replay stale direction authority

Family switch uses the existing hot strategy-switch lifecycle, not a broker trade.

Legacy strategy selector remains under settings for compatibility. Do not remove until old pilots/history are deliberately migrated.

---

## 5. Generic X + TakeProfit is production architecture

TakeProfit is **not a strategy key**. It is a generic modifier around any X.

Implementation:
`autotrader_take_profit_modifier_v1.py`

UI:
`tradingdesk_automanager_simple_v1.py`

Contract:

`exit floor = peak profit (MFE) * (1 - giveback fraction)`

Examples:
- peak +1.00%, 10% giveback -> FLAT floor about +0.90%
- peak +1.00%, 5% giveback -> FLAT floor about +0.95%

User settings:
- enabled/disabled
- allowed giveback %
- minimum peak-profit before arming
- re-entry cooldown seconds

Why minimum peak exists:
without an arming threshold, 5–10% of a microscopic positive P/L becomes spread/noise churn.

LIVE behavior:
- tracks actual Saxo position P/L/high-water
- latches FLAT after trigger
- base strategy cannot immediately undo the close
- re-entry is blocked for configured cooldown
- actual order still goes through normal durable execution

SIM behavior:
- `apply_take_profit_replay_v1(...)` wraps arbitrary `PRICE/TARGET` strategy frames
- Strategy Lab can compare X vs. X+TakeProfit

Family switches preserve TakeProfit config on the target pilot. This is regression-tested.

Default is opt-in:
`enabled=False`

Do not bake TakeProfit into MACD/Price+MACD/Price+Stoch logic. Keep it a modifier.

---

## 6. MACD authority bug that was fixed

A major live failure was traced to supervisor logic that could remain SHORT after MACD had already crossed UP, because slow context / score / hysteresis could veto the actual crossover.

PR #406 fixed the contract:
- supervisor may anticipate a 5m cross and switch earlier
- once closed 5m MACD crosses:
  - `CROSS_UP -> LONG`
  - `CROSS_DOWN -> SHORT`
- slow context may not veto the confirmed cross
- manager/cooldown may not delay the confirmed cross
- a newer cross may supersede an older pending transition through the hardened lifecycle
- same-direction confirmation preserves entry/MFE instead of resetting it

Pure MACD timeframe family now generalizes this closed-bar authority to selected N-minute timeframe.

Do not reintroduce score-as-veto behavior.

---

## 7. Runtime watchdog / flight recorder

A read-only watchdog now observes production every ~15 seconds.

Implementation:
`autotrader_runtime_watchdog_v1.py`

Started from the stream-worker runtime.

It independently observes:
- active LIVE enrollment
- desired target
- pending target
- actual Saxo exposure
- durable execution request/status
- relevant authoritative MACD cross for MACD controls/family
- TakeProfit effective FLAT authority

It persists:
- open/resolved findings
- compact reports
- heartbeat/status

Runtime Diagnostics exposes copyable/shareable reports.

Important anomaly classes include:
- authoritative cross not acknowledged
- target vs Saxo exposure opposite after grace period
- target not reached
- pending transition stuck
- execution request stuck in ambiguous states

Logs use searchable markers such as:
- `WATCHDOG anomaly`
- `WATCHDOG resolved`
- `WATCHDOG summary`

When a user reports “something went wrong around HH:MM”, search Railway logs/watchdog persistence first rather than reconstructing from screenshots.

The watchdog has **no execution authority**.

---

## 8. Live chart: actual root cause and current fix

This took several iterations. The final root cause was not the feed.

Backend evidence showed:
- Saxo chart events arriving at ~1000 ms
- canonical bars advancing normally
- visible mobile chart still frozen

The actual issue:
**Streamlit components v2 are iframe-isolated.**

Earlier architecture mounted:
- visible Lightweight chart in one bidi component
- zero-height live/base updater components in other bidi components

Those updater iframes tried to mutate the visible chart through:
`window.__pricegaugerLightweightCharts`

But each iframe has its own `window`. Therefore the updater could never reach the actual visible chart.

PR #416 fixes this correctly:

- **one visible component owns the chart**
- canonical candles, indicators, markers and forming candle are in the same payload/component
- visible component owns the 1s browser heartbeat
- no cross-iframe updater is used
- 5s Streamlit chart fragment remains fallback
- forming 1m candle is aggregated into the currently selected timeframe bucket
  - correct open/high/low/close for 2m/5m/10m/etc.
- no full-page `st.rerun()` loop
- no chart remount should be required for normal live formation

Relevant files:
- `pages/0_TradingDesk.py`
- `tradingdesk_ui/charts/lightweight/direct_contract.py`
- `tradingdesk_ui/charts/lightweight/direct_runtime.py`

Do **not** revive the separate `live_update.py` / `base_update_v1.py` cross-iframe approach as the main solution.

At this handoff the user is visually validating the chart on mobile; the backend/deploy is healthy. If the UI still freezes, debug the single visible component lifecycle first.

---

## 9. Trade markers / FLAT / manual fills

Current chart semantics include:
- strategy trade markers
- FLAT markers
- manual Saxo fills as distinct markers

Recent relevant PRs:
- #402 — FLAT squares, Close position, live marker refresh
- #409 — manual Saxo fills as distinct live chart markers

User requested FLAT to be visually distinct; preserve this.

---

## 10. AutoManager UX contracts

Normal simple path in TradingDesk:
- BUY
- SELL
- Manage position
- AutoTrade
- strategy-family builder
- optional settings

Manual BUY/SELL goes through the durable manual-target lifecycle.

“Close position” exists and must not be conflated with disabling AutoTrade.

Backend enrollment is authoritative across browser/session reruns. A stale selectbox/session state must never silently switch a live strategy.

Current family builder:
- family selector
- timeframe selector
- custom timeframe
- `SIM / LIVE` multiselect
- explicit Apply button
- current SIM and LIVE labels

TakeProfit is in optional settings.

---

## 11. Production safety invariants — do not break these

### Execution
Never allow a strategy to submit directly to Saxo.

All transitions must go through durable execution requests and the hardened lifecycle:
`CLOSE -> confirmed FLAT -> OPEN`

### Exact product identity
Saxo authority must remain tied to exact:
- account
- UIC
- asset type

Do not infer position direction from a visually similar market name.

### Ambiguous broker states
Do not mutate strategy ownership/parameters while an order is:
- `SUBMITTING`
- `ORDER_ACCEPTED`
- `UNCERTAIN`

### Newer signal authority
A newer valid strategy signal may supersede an older unstarted intent, but must not pretend an already-submitting broker request never existed.

### No stale replay after family/timeframe change
Supersede unstarted intents, clear runtime state, bootstrap from actual Saxo exposure.

### Strategy vs manager separation
Base strategy decides market target.
Generic modifiers manage held-position behavior.
Execution decides how to reach the target safely.

Do not collapse these layers again.

---

## 12. What is already done — do not rebuild

The following are implemented on current `main`:

- autonomous LIVE authority for supported strategies
- exact-product Saxo reconciliation
- direct BUY/SELL controls
- Close position
- FLAT chart markers
- manual fill markers
- second-level forming candle data path
- single-component live-chart formation
- selectable chart timeframe
- Price + Stoch half-parade
- Price + MACD family
- parameterized MACD family
- timeframe presets + custom 1–240m
- SIM / LIVE / both activation
- hot strategy switching
- generic X + TakeProfit
- TakeProfit SIM wrapper
- TakeProfit LIVE P/L/MFE tracking
- TakeProfit re-entry cooldown
- runtime watchdog / flight recorder
- watchdog Runtime Diagnostics UI
- persistent family config
- regression tests for family parameter propagation into SIM and LIVE

---

## 13. Recommended next work

### A. User-facing validation first

Before extending architecture, validate the just-landed interfaces on the actual mobile production UI:

1. Live chart visibly forms candle second-by-second after one reload.
2. Chart continues into the next candle without full page refresh.
3. Selected timeframe forms the correct bucket.
4. Family UI can:
   - select MACD / Price+MACD / Price+Stoch
   - select preset timeframe
   - enter custom timeframe
   - select SIM / LIVE / both
   - Apply explicitly
5. LIVE label reflects backend truth after rerun/device change.
6. TakeProfit settings survive family switch.
7. Watchdog remains quiet during correct transitions.

If anything fails, fix observed behavior before expanding feature surface.

### B. Family architecture cleanup

Good next architectural cleanup:
- make strategy-family UI the obvious primary strategy control
- demote the flat legacy strategy dropdown further into “legacy/advanced”
- show effective strategy identity consistently:
  - e.g. `Price + MACD · 5m + TakeProfit(10%)`
- use the same display identity in:
  - AutoManager
  - Strategy Lab
  - watchdog reports
  - trade markers/logs where useful

### C. Price + Stoch timeframe generalization

Price + Stoch is intentionally fixed to 1m in v1.

A likely next experiment is allowing stochastic/price-vector timeframe configuration, but do not blindly reuse MACD timeframe semantics. Decide whether:
- stochastic slope is computed on raw 1m while price confirmation uses N-minute context, or
- the entire stochastic-vector family moves to N-minute aggregation

Test in SIM before expanding LIVE.

### D. Modifier architecture

TakeProfit proves the wrapper model.

Future position-management features should preferably be modifiers rather than strategy-key explosions:
- trailing profit variants
- stop-loss / catastrophe stop
- breakeven reset
- volatility-dependent giveback
- partial de-risking if Saxo/product supports the desired semantics safely

Keep modifiers composable and auditable.

### E. Performance evidence

Now that family/timeframe selection is parameterized, build comparisons around:
- return
- max drawdown
- capture
- switch count/churn
- time from actual move onset to target change
- amount of MFE given back before exit
- behavior in trend vs. chop

Do not optimize only win rate.

### F. Clean stale research

Review draft PR #405. It predates the corrected MACD authority model and likely should be closed unless its “large-move escape” experiment still has independent research value.

---

## 14. Important conceptual direction from the user

The user's current strategy intuition is deliberately simple:

> Ultimately P/L comes from whether price goes up or down.

The architecture should therefore avoid indicator absolutism.

Current intended hierarchy for price-first models:

- **Price = authority**
- **Stochastic = scout / half-parade**
- **MACD = confirmation / fallback**
- **TakeProfit = held-position profit protection**

For pure `MACD(N)`, however, a closed MACD cross remains the explicit strategy authority by definition.

Do not accidentally apply the price-first rule to pure MACD and thereby change its meaning.

---

## 15. Useful files to read first

Core execution/safety:
- `autotrader_fast_live_runtime_v2.py`
- `autotrader_strategy_switch_v2.py`
- `autotrader_automanage_dispatch_v2.py`
- `autotrader_strategy_enrollment_v2.py`

Strategy families:
- `autotrader_strategy_family_v1.py`
- `tradingdesk_strategy_family_ui_v1.py`
- `autotrader_family_replay_v1.py`
- `autotrader_macd_timeframe_live_v1.py`
- `autotrader_price_macd_v1.py`
- `autotrader_price_macd_live_v1.py`
- `autotrader_price_stoch_v1.py`
- `autotrader_price_stoch_live_v1.py`

Position management:
- `autotrader_take_profit_modifier_v1.py`
- `autotrader_risk_control_v2.py`

Diagnostics:
- `autotrader_runtime_watchdog_v1.py`
- `pages/99_Runtime_Diagnostics.py`

TradingDesk/live chart:
- `pages/0_TradingDesk.py`
- `tradingdesk_automanager_simple_v1.py`
- `tradingdesk_ui/charts/lightweight/direct_contract.py`
- `tradingdesk_ui/charts/lightweight/direct_runtime.py`

Tests:
- `tests/test_autotrader_strategy_families_v1.py`
- `tests/test_autotrader_take_profit_modifier_v1.py`
- `tests/test_autotrader_runtime_watchdog_v1.py`
- live chart tests under `tests/test_live_chart_*.py` and `tests/test_tradingdesk_lightweight_chart_v1.py`

---

## 16. Working style for Arkitekt 13

The user expects the architect to be the coder:
- inspect repo/runtime directly
- make the change
- keep CI moving instead of stopping the conversation
- ask the user only when external/product judgment is actually needed
- when CI runs, use that time for self-review, fresh-main checks, runtime inspection, or the next safe task
- prefer small separated PRs when signal logic, position management, execution, and UI can be tested independently

For live behavior, verify production rather than assuming merge success implies runtime success.

---

## 17. First action for Arkitekt 13

1. Refresh `main`.
2. Confirm SHA is at least `97561cdb32eaee5174fd3fb6d5105f26bac59ade`.
3. Read this handoff plus:
   - `autotrader_strategy_family_v1.py`
   - `tradingdesk_strategy_family_ui_v1.py`
   - `autotrader_take_profit_modifier_v1.py`
   - `autotrader_runtime_watchdog_v1.py`
   - `direct_contract.py` / `direct_runtime.py`
4. Check Railway service health and recent `WATCHDOG` anomalies.
5. Ask the user only for what they can uniquely observe in the UI; otherwise inspect/fix directly.
6. Continue from the user-facing validation / family cleanup backlog above.

The system is in a substantially better state than earlier September: the main remaining work is now refinement, evidence, and UI/strategy-model consolidation rather than rebuilding the execution foundation.
