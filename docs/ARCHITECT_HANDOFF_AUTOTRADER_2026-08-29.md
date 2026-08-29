# PriceGauger Architecture Handoff — AutoTrader live pilot

Date: 2026-08-29

This is the operating handoff for the next PriceGauger architect. The project has reached a deliberate pause point in analysis/product-browser work. The critical path is now **closing the execution loop safely enough to run a tiny real-money autonomous pilot**.

## 1. Canonical repo state

Repository: `oveaignerhaukenes-lgtm/PriceGauger`

Canonical `main` at handoff:

`4b8e5b4ef3f6ba52c5683bf6b0baf71184ba4449`

This includes merged PR #221, which adds the first closed-30m MACD LONG/SHORT flip policy. CI was green before merge.

Relevant recent PRs:

- #217 — explicit AutoTrader vs Position Guardian authority modes.
- #218 — deterministic Technical Guardian HOLD/REDUCE/CLOSE policy.
- #221 — closed 30m MACD 12/26/9 LONG/SHORT flip intents and CLOSE -> confirmed FLAT -> OPEN planning.
- #216 and prior — financial-property Product Browser, fractional index-CFD probing, margin/cost discovery.

Related architecture issue:

- #219 — `strategy pump + capital valve` concept.

## 2. Immediate product goal

The next milestone is intentionally small and empirical:

> Put roughly 500 NOK of real capital under AutoTrader control on one explicitly allowlisted, low-friction index CFD and let it alternate LONG/SHORT using only confirmed closed 30m MACD crosses. Measure whether the capital rises or falls and why.

There is already a small live position (around 340 NOK) in an Australia/technology/index-style Saxo product visible to PriceGauger. Do **not** infer identity from the display name. Resolve the exact UIC + AssetType through the canonical Saxo/instrument mapping before arming anything.

The pilot is successful as an engineering test if PG can autonomously execute the lifecycle correctly and audibly, even if the trading result is negative. Profitability is a later calibration question.

## 3. Two user-facing execution products

### AutoTrader

Full lifecycle authority, but only inside explicit hard gates:

`OPEN -> ADD -> REDUCE -> CLOSE`

AutoTrader may choose direction from a strategy pump and later choose among a bounded PG Product Universe. It never chooses its own risk limits.

### Position Guardian

Manages a position that the user already owns/enrolled.

Default authority:

`HOLD -> REDUCE -> CLOSE`

No unrelated entry and no ADD.

An optional Protect + Flip mode may later open the opposite direction, but only after:

1. the managed position is closed,
2. Saxo confirms FLAT,
3. a fresh opposite entry decision is produced,
4. all ordinary OPEN gates pass.

Never reverse in one order.

## 4. Core separation: Pump vs Valve

This is now an explicit architectural concept and should remain separate.

### Pump

A strategy/regime-specific signal generator that proposes desired exposure and timing.

First pilot pump:

- canonical market history only,
- fully closed 30m bars,
- MACD 12/26/9,
- cross-up => desired LONG,
- cross-down => desired SHORT,
- no pyramiding from repeated same-side signals,
- no LLM,
- no Context/Bias/Macro.

Later pumps may include trend-following, range, breakout, holistic TA/AI, or context-aware strategies.

### Valve

Strategy-agnostic capital/position lifecycle + safety layer.

Responsibilities include:

- translate desired exposure to bounded lifecycle actions,
- enforce CLOSE -> confirmed FLAT -> OPEN on reversals,
- apply Product Universe allowlisting,
- apply Margin Envelope,
- run Saxo precheck,
- enforce idempotency/audit trail,
- prevent stale-signal re-entry after a hard safety stop,
- later support high-water / bounded-giveback semantics.

The pump can be replaced without rebuilding the valve.

## 5. Existing strategy-side building blocks

### `autotrader_macd_dry_run_v2.py`

Existing canonical 30m MACD machinery:

- resamples canonical 1m history,
- uses only fully closed UTC/epoch-aligned 30m bars,
- MACD 12/26/9,
- deterministic cross detection,
- persisted dry-run state/events.

Historically this was LONG/FLAT only. Do not duplicate its bar construction or MACD math.

### PR #221 flip policy

The new policy reuses the closed-bar MACD observations but emits LONG/SHORT intent for the live-pilot architecture.

Key invariants:

- cross-up -> LONG intent,
- cross-down -> SHORT intent,
- same-side intent -> HOLD,
- opposite direction -> controller returns CLOSE first,
- only a later cycle with **observed confirmed FLAT** may OPEN the opposite direction,
- a hard stop cannot immediately reopen from a stale pre-stop signal; a fresh cross is required.

This PR adds no Saxo order authority by itself.

### `autotrader_position_controller_v2.py`

Canonical strategy-to-lifecycle translator.

It is deliberately product-agnostic and already supports:

- HOLD,
- OPEN,
- ADD,
- REDUCE,
- CLOSE,
- incremental target fractions,
- close-first reversal semantics.

Do not bypass this controller with strategy-specific direct order submission.

## 6. Existing LIVE execution safety

There is already proven Saxo LIVE close capability. Despite legacy-ish filenames, these paths are active and execution-sensitive.

Important existing constraints include:

- LIVE environment verification,
- explicit code/environment gate,
- global execution arming,
- per-position enrollment/management,
- current-position reread before execution,
- strict UIC / AssetType / direction / amount / entry identity matching,
- Saxo precheck,
- no unresolved disclaimers,
- idempotent attempt persistence before POST,
- explicit uncertain/reconciliation states,
- no blind retry after uncertain submission,
- risk reevaluation immediately before close.

Do not weaken these to make the pilot easier.

Direction reversal must remain two independent audited operations:

`CLOSE -> reconcile FLAT -> fresh OPEN`

## 7. Margin is the execution resource

Margin is **not** strategy-selected gearing.

The strategy asks for desired direction/exposure. The execution layer determines the largest legal order inside a hard Margin Envelope.

The current architecture distinguishes at least:

- capital control limit,
- maximum initial margin,
- maximum notional exposure,
- maximum effective leverage,
- minimum free capital.

A strategy cannot infer "10% margin means I may use 10x". Sizing is downstream and fail-closed.

For the small pilot, keep the limits intentionally tiny and explicit. The user is comfortable with roughly 500 NOK being the experimental capital, but exact execution settings should still be visible and armed explicitly.

### Negative balance assumption

Development may proceed on the working assumption that the user's ordinary Saxo retail account has negative-balance protection. The user intends to verify this manually with Saxo.

Do **not** encode negative-balance protection as a guaranteed execution invariant until account status/product scope is verified. Even after verification, treat it as catastrophe protection, not risk management.

## 8. Product Browser status and philosophy

Product discovery changed direction successfully.

Do not make Saxo product taxonomy the primary UI. `CFD`, `ETF`, `Turbo`, `MiniFuture`, `FxSpot`, etc. are metadata, not the user's main decision model.

The browser should increasingly rank/filter by financial properties such as:

- minimum viable trade size,
- actual initial/maintenance margin,
- spread,
- explicit commission,
- round-trip friction / break-even move,
- LONG + SHORT availability,
- fractional sizing,
- effective gearing/notional,
- liquidity/spread stability,
- trading hours,
- overnight financing,
- expiry/rollover/KO properties.

Index CFDs are currently the most promising **training universe** because several Saxo Index Tracker CFDs appear to support fractional sizes (e.g. 0.01) with spread-based pricing and no fixed ticket fee.

Gold/Brent remain attractive production markets later, but their minimum margin/contract sizes are too large for the smallest training account.

Architecture flow:

`Saxo -> Product Browser -> PG Product Universe -> AutoTrader`

AutoTrader should consume an approved universe, not browse arbitrary Saxo instruments directly.

Future Product Browser enhancements, **not current critical path**:

- favorites,
- saved product lists,
- user trading mandate/profile,
- account-size-driven suitability search.

## 9. Analysis stack status

The analysis side is good enough to pause.

Technical Core is deterministic/auditable. TA Analyst can produce holistic technical-only multi-scenario analysis. Forecast graph/ghost work is usable. Do not reopen large analysis/UI work until the execution pilot is functioning unless a blocking bug appears.

Longer-term architecture remains layered:

- Market Data -> Technical
- user-curated Telegram/news -> Bias
- broader news/events -> Context
- Bias + Context -> Biased Context
- multi-market -> Cross-market
- canonical Saxo identity -> Execution
- later Synthesis combines independent specialist outputs.

No foundational layer should secretly read another domain's data.

The future mixer/routing idea is already documented in `docs/PRODUCT_IDEAS.md`: raw structured outputs and AI interpretation should remain separately routable downstream.

## 10. Context-aware trading is later, not the first pilot

The eventual aim is not technicals in isolation. Technicals should operate inside a contextual regime that can react to macro, monetary policy, geopolitics, news, etc.

Example future behavior:

- a material geopolitical event changes expected price response,
- Context detects the regime change,
- the active pump or Synthesis changes positioning priors,
- Technical remains responsible for timing/structure confirmation,
- Valve still owns exposure/risk/execution.

Do not add this to the first MACD pilot. First prove the valve and live lifecycle on a deterministic pump.

## 11. New control idea: target capture fraction, not an abstract risk slider

A useful future user-facing strategy control is **how much of a market move the system is trying to capture**, rather than an opaque "risk = 7/10" input.

Conceptually:

- low target capture (e.g. "capture only a small central part of the move") permits late confirmation and early exit,
- medium target capture requires earlier entry / later exit,
- aggressive target capture seeks more of the slope and therefore relies on less-confirmed turning-point estimates,
- trying to capture ~100% of every move effectively requires predicting each turn and becomes lottery-like.

Important: the future move is unknown ex ante, so do **not** implement this as a literal guaranteed percentage of a realized future slope. Treat it as a strategy-aggressiveness contract that maps to measurable entry-confirmation and exit/giveback behavior and can later be calibrated empirically by regime.

A practical implementation path later may expose a `capture_target` that influences:

- how much confirmation is required before entry,
- how early the system accepts partial profit,
- allowed giveback from local/high-water profit,
- sensitivity to reversal evidence,
- re-entry patience.

This complements, not replaces, hard Margin Envelope limits. "Desired capture" is strategy behavior; hard capital/margin limits remain execution safety.

## 12. Next bounded capabilities — recommended order

### Step 1 — live pilot runtime wiring

Create a runtime that binds:

`canonical Saxo position/instrument -> market_id -> canonical history -> MACD flip policy -> PositionTargetV2 -> position controller`

Persist each evaluation/intent/decision with provenance.

No order submission yet unless the execution adapter is explicitly invoked through the ordinary gates.

### Step 2 — REDUCE/CLOSE integration

Reuse the proven LIVE close path and add bounded reduce-only behavior where needed.

Hard invariant: REDUCE can never increase exposure or reverse direction.

### Step 3 — LIVE OPEN adapter

This is the first genuinely new high-risk execution capability.

Requirements before POST:

- exact canonical UIC + AssetType,
- explicit Product Universe allowlist,
- one selected pilot product,
- account/market currently tradable,
- strategy intent still fresh,
- observed position confirmed FLAT for a reversal,
- Margin Envelope passes,
- Saxo order precheck passes,
- no unresolved disclaimer,
- idempotent attempt record created before submission,
- no blind retry after uncertain response,
- reconciliation against live Saxo state.

Do not add generic arbitrary Saxo OPEN access.

### Step 4 — arm one-product 30m MACD pilot

Start with the existing account-visible low-friction index CFD if it passes all checks.

Initial pilot behavior:

- one market/product only,
- LONG on confirmed closed 30m MACD cross-up,
- SHORT on confirmed closed 30m MACD cross-down,
- same-side signal => HOLD,
- reversal => CLOSE -> FLAT confirmation -> OPEN opposite,
- hard safety stop requires a fresh cross before re-entry,
- no AI overrides,
- no Context/Bias,
- no multi-market selection,
- no incremental pyramiding initially unless separately approved.

### Step 5 — empirical evaluation

Log enough to answer why the account moved:

- input bar time,
- MACD / signal values,
- cross direction,
- target direction,
- observed live position before action,
- lifecycle decision,
- Product Universe decision,
- margin envelope result,
- precheck result,
- requested amount,
- order/fill/reconciliation,
- spread/cost/slippage,
- realized P/L,
- strategy equity/high-water,
- reason for any block.

Evaluate failure modes before adding sophistication:

- too many flips/chop,
- late entries,
- late exits,
- spread consuming edge,
- stale-data timing,
- trend vs range behavior,
- weekend/overnight behavior,
- insufficient position granularity.

## 13. What not to do next

Do not:

- build the full Synthesis/Mixer now,
- add Context/Bias to the first pilot,
- let an LLM directly place or size orders,
- make strategy code choose gearing,
- weaken the LIVE close safety path,
- bypass confirmed-FLAT reversal sequencing,
- broaden Product Universe just to obtain more candidates,
- preserve obsolete code "just in case" if a cleaner canonical path replaces it,
- undertake another broad architecture rewrite.

The operating principle remains:

> Preserve correct function and correct data, not old implementations.

## 14. User intent / acceptance criterion

The user's near-term problem is practical: good market analysis is often undermined by being away from the screen while a technically obvious adverse move develops. PriceGauger should first become capable of **mechanically handling the obvious lifecycle decisions** while unattended.

The first autonomous pilot is therefore intentionally not a claim of profitable AI trading. It is a controlled test of whether PG can act as a reliable valve around a simple pump.

Once the simple MACD pump can run live safely, strategy quality can be improved one bounded layer at a time.
