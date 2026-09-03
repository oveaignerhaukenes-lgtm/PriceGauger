# PriceGauger Architecture Handoff — 2026-09-03

This is the authoritative handoff snapshot for the next PriceGauger architect after the AutoManager lifecycle hardening, TradingDesk persistence work, and first Cocktail Mode #1 shadow deployment.

Always refresh from `main` before starting new work. The SHA below is the exact baseline at handoff creation, not a permanent pin.

## 1. Authoritative starting point

Repository: `oveaignerhaukenes-lgtm/PriceGauger`

Canonical `main` at handoff creation:

`c45de4a720aafaefcca8e1a6d8821d12f807bf6a`

This is the merge of PR #276: **TradingDesk: make workspace restore widget-safe**.

Railway production project:

- project: `482dad8f-efc5-415a-b1f7-99f45cb2bd7b` (`grateful-reflection`)
- production env: `9a9b7cc6-1dd0-4044-a0f0-221b06138e8f`
- `pricegauger-web`: `38f57908-1f7a-40ce-9bf4-abcdf43fe429`
- `PriceGauger-stream`: `0be7cd65-533f-4882-9b81-efeda5b35153`
- `PriceGauger-worker`: `5267feed-b5cb-4f85-a24a-0c5124664b59`
- `Postgres`: `a7a66447-8138-4ea9-94b0-5df0c291f337`

Fresh production snapshot on the morning of 2026-09-03:

- US Tech 100 canonical 1m feed is fresh.
- Saxo UIC 4912 is net `SHORT 0.03` at snapshot time.
- Saxo intraday netting showed `AmountLong=0.08`, `AmountShort=0.11`, signed `Amount=-0.03`; stale `OpeningDirection=Buy` must not be trusted as net direction.
- RiskControl saw one position and `close_signals=0`.
- Cocktail Mode #1 shadow is producing observations for six of seven configured markets. `sp500 CFD` still hits the known `invalid 5m ATR` error.

Do not treat the fresh position snapshot as a permanent state; re-read Saxo before making any execution-related conclusion.

## 2. Current pilot and capability boundaries

Canonical live pilot product:

- market: `US Tech 100 NAS · Saxo 4912`
- account: `1068427INET`
- UIC: `4912`
- AssetType: `CfdOnIndex`
- active LIVE strategy: `macd-mtf-30-10-5-long-short-v1`
- label: `MTF 30/10/5 · long/short flip`

Keep capability names distinct:

### Position Guardian / RiskControl

Defensive only. It may observe, reduce or close exposure under explicit defensive policy. It must never create or increase exposure.

### AutoManager

Manages one selected product mandate. It may close and, under explicit OPEN authority, re-enter or flip through the canonical lifecycle.

### AutoTrader

Future broader origination layer inside explicitly approved product/capital/risk mandates. Do not collapse it into AutoManager or Guardian.

## 3. Core execution invariants — do not weaken

Preserve all of these:

- no LLM order placement or sizing
- no strategy-selected leverage
- no arbitrary generic Saxo OPEN path
- exact account + UIC + AssetType + direction Product Admission
- one active LIVE controller per exact product
- CLOSE authority and OPEN authority are separate
- reverse only as `CLOSE → confirmed FLAT → OPEN opposite`
- never one-order reverse
- settled authoritative close/P&L provenance before re-entry
- current settled pilot equity reread before sizing
- realized P/L adjusts pilot equity; unrealized P/L does not compound it
- final Saxo precheck immediately before POST
- durable execution attempt before POST
- uncertain submit is never blindly retried
- stale signal cannot revive after risk-origin flattening
- entry-mode/authority changes invalidate prior OPEN authority
- no pyramiding
- Product Admission remains direction-specific

Entry modes remain:

- `MANUAL_ENTRY_ONLY`
- `AUTO`
- `APPROVAL_REQUIRED`

Sizing modes remain:

- `MAX_WITHIN_PILOT`
- `FIXED_AMOUNT`

Saxo sizing rules already hardened: `DefaultAmount` is not minimum size; `IncrementSize` is not amount increment; `AmountDecimals` is precision only; explicit minimum fields are hard bounds; account/product-specific Saxo precheck is final authority.

## 4. Recent AutoManager lifecycle fixes

### PR #271 — pilot resume + PostgreSQL evaluator

Two real production bugs were fixed:

1. Re-enabling an existing canonical pilot tried to reseed it from the UI default (`500`) and failed because the historical ledger had a different immutable seed.
2. MTF evaluation crashed every ~15 seconds in PostgreSQL with `could not determine data type of parameter $5`.

Current contract:

- disabled canonical pilot resumes the existing ledger instead of being recreated
- existing entry-mode is preserved
- OPEN remains deliberately disarmed on resume until explicitly re-armed
- ambiguous nullable SQL path was split so PostgreSQL gets typed parameters

### PR #273 — strict close/P&L provenance fallback

A close could be Saxo-reconciled while realized P/L settlement remained stuck if Saxo omitted `ClosingExternalReferenceId` from the closed-position row.

Primary matching remains ExternalReference. Strict fallback is now:

`exact Saxo OrderId → OrderActivities FinalFill PositionId → exact ClosingPositionId`

It still requires the correct account/UIC/AssetType/amount. No fuzzy time/price matching was introduced.

### PR #274 — carried flip OPEN race

A valid reversal could do CLOSE correctly, then evaluate the carried OPEN before close/P&L reconciliation finished. The OPEN saw the old position and became terminally `PRODUCT_NOT_CONFIRMED_FLAT` even though the product became FLAT seconds later.

Current ordering:

- exact unresolved close/reconciliation gate is checked before product-position rejection
- legitimate carried flip request stays PENDING while its close settles
- once FLAT + authoritative P/L are proven, ordinary OPEN gates continue
- unrelated existing exposure still blocks terminally
- `STALE_ENTRY_SIGNAL` deliberately remains terminal

The intended lifecycle is now mechanically:

`signal → CLOSE → confirmed FLAT → authoritative P/L settlement → opposite OPEN`

The next architect should continue observing natural LIVE reversals to prove this repeatedly without manual intervention.

## 5. Saxo netting direction — important

Saxo intraday netting may retain gross long/short amounts and an `OpeningDirection` that does not describe current net exposure.

PG now resolves direction primarily from:

- `AmountLong`
- `AmountShort`
- signed `Amount`

and cross-checks `OpeningDirection` rather than trusting it.

Examples:

- long 0.08 / short 0.11 / signed -0.03 → `SHORT 0.03`
- equal gross long/short and signed zero → confirmed `FLAT`
- material disagreement/ambiguity → fail closed

Logs still noisily warn about “mixed long/short exposure” when Saxo gross intraday sides accumulate. Direction resolution itself is correct; logging/normalization can be cleaned up later.

## 6. Current LIVE MTF limitation: bar-close latency

The active MTF LIVE strategy is still based on fully closed timeframe bars:

- closed 5m trigger
- closed 10m validation
- closed 30m confirmation
- a fully closed opposite 30m cross is the event allowed to carry a LONG↔SHORT reversal target through CLOSE→FLAT→OPEN

This is no longer considered the desired signal basis.

User principle going forward:

> The relevant canonical event is the MACD cross timestamp, not the candle-close timestamp.

Reason: bar-close gating introduces arbitrary latency. A 30m cross one minute before bar close waits ~1 minute; a cross one minute after a new bar begins waits almost 29 minutes. That contaminates strategy evaluation with candle-boundary timing.

Existing technical proof already exists in `autotrader_intrabar30_shadow_v2.py`: forming 30m MACD is recalculated on each fully observed canonical 1m close and cross timing is recorded. General direction should be:

`indicator horizon (5/10/15/30m) != observation cadence (canonical 1m)`.

Do not silently change LIVE MTF semantics without a bounded capability and tests. Cocktail Mode already implements the newer observation model in SHADOW.

## 7. Cocktail Mode #1 — current strategic center

PR #272 introduced `Cocktail Mode #1` as a full **SHADOW ONLY** engine.

Relevant files:

- `docs/COCKTAIL_MODE_1_V1.md`
- `autotrader_cocktail_mode_1_shadow_v2.py`

It is intentionally NOT in the LIVE strategy catalog, has no execution request authority, and starts with `BOOTSTRAP_NO_REPLAY`.

User considers this much closer to the intended end-state than the earlier simple MACD state machines. Do not do a large architecture refactor before the strategy end-state is clearer; the architecture should eventually be reorganized around the engine we actually want.

### Canonical data basis

- one canonical closed 1m observation clock
- forming 5m / 10m / 15m / 30m MACD recalculated at each new canonical 1m point
- cross event is the first observed sign change, not the enclosing candle close
- store observed cross time and an optional interpolated analytical estimate only when data is contiguous
- data gaps must not fabricate precision

### Explicit modes

- `NORMAL`
- `SHOCK`
- `TREND_LOCK`
- `WHIPSAW`

`FLAT` is an active decision state, not merely absence of a trade.

Core asymmetry: it should take less evidence to move from exposure to FLAT than to commit to the opposite side.

### Behavioral idea

- low activity + 5m/10m disagreement → FLAT/pause
- ordinary adverse 5m cross → normally FLAT, then wait for 10m confirmation
- strong 30m trend (`TREND_LOCK`) ignores ordinary 1m/5m counter-noise; 10m can flatten and 15m can confirm reversal
- `SHOCK` can override slower technical state when price/activity/S-R/fast MACD together indicate a genuine abrupt change
- `WHIPSAW` goes FLAT and requires a defined escape threshold before exposure resumes

Feature set includes ATR-normalized displacement, activity, directional efficiency, support/resistance break/distance, MACD spread and velocity by horizon. Threshold set is versioned as `CM1-2026-09-02-v1`.

A DB contract test caught a real 53-placeholder/52-parameter INSERT bug before production; persistence placeholders are now generated from params. 15m velocity was also corrected to use ATR15.

### Fresh shadow behavior

On US Tech overnight, Cocktail produced the sort of path the model was designed for: bearish 5m information led to FLAT/wait, later 10m bearish confirmation led to SHORT, with later SHOCK/30m confirmation. User has observed Cocktail appearing materially better than the simpler models so far. Treat this as promising early evidence only; do not claim positive expectancy from this short sample.

Known current Cocktail runtime issue: `sp500 CFD` repeatedly fails on `invalid 5m ATR`; fix this as a bounded shadow/data-quality issue.

## 8. Next Cocktail refinement: price must qualify MACD

A newly identified failure mode is important: `MACD - signal > 0` can coexist with falling price while the MACD complex remains below zero. That is often “bearish momentum is cooling” rather than “bullish regime”.

Cocktail should explicitly separate:

- `REGIME`: MACD level relative to zero
- `IMPULSE`: MACD relative to signal
- `PRICE CONFIRMATION`: what price is actually doing

Preferred rule of thumb:

> MACD describes momentum state; price decides whether that signal earns execution authority.

Add direct price features before granting EMA/RSI/Stoch execution authority:

- ATR-normalized price return/slope
- HH/HL vs LH/LL structure
- support/resistance breaks
- directional efficiency
- explicit `momentum_price_divergence` such as bullish MACD spread while price keeps making local lows

EMA may be a secondary stabilizer, but should not replace direct price truth with another lagging indicator. RSI/Stoch can be logged as candidate features first, then promoted only if data shows incremental value.

## 9. “Gin Tonic” successor concept — not implemented

A later voice discussion named a possible successor/evolution **Gin Tonic**.

This is only a concept, not code or authority.

Direction:

- model independent evidence classes: regime, momentum, price structure, volatility/activity, and later additional indicators/context
- indicators provide evidence rather than each acting as a binary trade switch
- aggregate evidence/confidence/score
- final state is still discrete `LONG / FLAT / SHORT`
- later exposure size may scale with multi-horizon agreement rather than being binary size only

User previously sketched a future graduated-exposure idea: small probe at very fast confirmation, then add as 10m/15m/20m/30m align, and reduce symmetrically as shorter horizons deteriorate. Do not implement this before the underlying signal engine is proven.

## 10. TradingDesk P/L and WorkspaceState

### PR #270 — durable product-history P/L

P/L history now survives strategy switches:

- actual realized Saxo P/L aggregated chronologically across persisted LIVE strategy pilots for the exact product
- strategy pilots remain separate for audit/runtime
- strategy attribution and strategy epochs are marked on the shared timeline
- linked x-axis/range behavior
- range controls and slider
- Europe/Oslo hover timestamps to seconds for TradingView correlation
- unrealized/open P/L is excluded
- product-based `uirevision` avoids resetting navigation on strategy change

### PR #275 / #276 — durable TradingDesk view state

DB-backed safe WorkspaceState currently persists:

- selected market
- chart timeframe
- MACD timeframe
- auto-refresh
- control-panel width

It must never persist or restore execution authority such as arming, entry mode, one-shot approvals, strategy activation, or order authority.

PR #276 fixed a Streamlit lifecycle bug where the persisted market key was rewritten after the selectbox widget had already been instantiated. Restore is now idempotent. User confirmed that TradingDesk market persistence works across navigation.

Persisted NBP verification is also no longer presented as a repeated checkbox once Product Admission already carries the verified state.

## 11. Known UI issue: active controller shown as activatable

Backend correctly enforces one active LIVE controller per product, but TradingDesk still can show `Aktiver AutoManager` for a product that already has a LIVE controller. Clicking it produces the backend error that an active controller already exists.

This is a UI/read-model bug, not an execution bug.

Desired UI:

- if selected strategy is the current controller: show `AutoManager kjører / Aktiv`; no activation flow
- if another strategy is selected while one controller is active: show the active strategy and offer only the existing safe LIVE strategy-switch flow, not a second enrollment
- do not show Startkapital/shadow/new-enrollment controls as though the product has no live pilot

An empty branch was created for this before the handoff request interrupted work:

`fix/tradingdesk-active-controller-state-v2`

It points at handoff-era main and contains no implementation. Reuse or delete it deliberately; do not assume a fix exists there.

## 12. Futures contract identity and rollover — important future capability

PriceGauger must distinguish **economic market identity** from **concrete tradable futures contract identity**.

Examples:

- analysis/reference may use a continuous symbol such as `BRN1!` or `GC1!`
- execution must always bind to a concrete Saxo contract/UIC, typically `AssetType=ContractFutures`
- a continuous/reference symbol must never become order identity

There is currently no dedicated automatic futures rollover engine in the repo.

### Required future ContractLifecycle/Rollover contract

1. Keep a stable economic market identity (`Brent`, `Gold`, etc.) across contract epochs.
2. Keep execution identity concrete and immutable inside an epoch: exact contract/UIC/AssetType.
3. Detect front-month/next-contract/expiry in an explicit lifecycle layer; do not hide it inside strategy logic.
4. Never silently mutate an active LIVE controller, Product Admission or audit identity from old UIC to new UIC.
5. A new execution contract requires fresh exact Product Admission, sizing/margin discovery and Saxo precheck.
6. If exposure exists in the expiring contract, rollover execution must still obey:
   `close old contract → reconcile → confirmed FLAT → settle P/L → optionally open new contract`.
7. Preserve P/L/audit continuity at the economic-market level while marking the contract rollover boundary explicitly.
8. Contract price gaps must not be interpreted as real market return, MACD shock or a strategy cross. Analysis needs adjusted/continuous provenance or explicit epoch handling.
9. TradingDesk should ideally remain on `Brent`/`Gold` while the concrete execution contract changes below the stable market identity.
10. Never carry a stale cross/reversal request blindly from the old contract into the new contract. Any cross-contract intent must be an explicit rollover policy.

This is a prerequisite before broad AutoManager/AutoTrader automation on expiring futures becomes trustworthy.

## 13. Architecture size / refactor decision

The project is getting broad, but test execution itself is still fast (the full suite was around ~13 seconds at ~1065 tests in the latest UI hotfix). Most elapsed development time comes from review, edge-case discovery, merge/deploy verification and increasingly broad module discovery.

There is real architectural friction from many flat `autotrader_*_v1/v2` policy/runtime/shadow files and strategy-specific plumbing.

Potential future cleanup:

- canonical Strategy Engine/interface
- strategies become mostly policy/config rather than bespoke execution runtimes
- clear `strategies / execution / runtime / reporting / ui` boundaries
- quick strategy/unit feedback plus mandatory full execution-contract gate
- first-class strategy laboratory over identical data and cost assumptions

However, the current product decision is explicit: **do not perform a large refactor yet**. First let Cocktail/end-state become clearer; then reorganize around the engine we actually want.

Also do not bulk-delete files because they end in `_v1`; several hardened production helpers still carry historical filenames.

## 14. V1 retirement

Historical PR #245 (`V2 cutover: quarantine retired v1 production paths`) must not be merged stale. If resuming this work, rebuild/rebase from fresh main and re-review active imports after all AutoManager changes.

The actual target is not “no files named v1”; it is no hidden legacy semantic authority, fallback or reinterpretation in the active v2 path.

## 15. Recommended next sequence

1. Fix the misleading active-controller TradingDesk UI as a small read-model/UI PR.
2. Observe the next natural MTF LIVE reversal and verify the complete #273/#274 chain without manual intervention.
3. Fix Cocktail `sp500 CFD invalid 5m ATR` without changing execution authority.
4. Add the Cocktail zero-line + direct-price + momentum/price-divergence refinement in SHADOW, with versioned thresholds/features.
5. Continue collecting Cocktail vs simpler-model evidence across different regimes. Do not optimize only for the unusual Iran/USA/news regime around initial testing.
6. Only after sufficient evidence, design a bounded promotion path for Cocktail to LIVE authority; do not copy/rewrite the execution stack.
7. Later formalize the broader Gin Tonic evidence-aggregation model.
8. Build explicit futures ContractLifecycle/Rollover before autonomous management of expiring futures.
9. Once the strategy/end-state is clearer, do the architecture maintenance/refactor sprint.
10. Still obtain a controlled process-restart/recovery LIVE proof. Code-level BOOTSTRAP_NO_REPLAY/recovery contracts are not the same thing as production proof.

## 16. Repository workflow

Continue the established discipline:

- fresh `main`
- one bounded capability per branch/PR
- focused tests plus full CI
- self-review of diff and authority impact
- fresh-main check before merge
- expected-head merge guard
- Railway verification for runtime changes
- production smoke logs for execution/reconciliation changes
- documentation-only changes do not require a runtime deployment proof beyond ordinary CI/merge hygiene

Do not weaken a safety gate merely to make a pilot “work”. A fail-closed state that exposes a missing provenance or lifecycle transition is preferable to a trade that cannot be audited.

## 17. Quick orientation

Read these first:

- `docs/ARCHITECT_HANDOFF_2026-09-03.md` — this document
- `docs/COCKTAIL_MODE_1_V1.md`
- `docs/MTF_FLIP_LIVE_V1.md`
- `docs/MTF_SHORT_LIVE_V1.md`
- `docs/AUTOMANAGER_PNL_PRODUCT_HISTORY_V2.md`
- `tradingdesk_automanage_panel_v2.py`
- `tradingdesk_autotrade_entry_gate_v2.py`
- `tradingdesk_workspace_state_v2.py`
- `ui_workspace_state_v2.py`
- `autotrader_mtf_flip_policy_v2.py`
- `autotrader_mtf_flip_live_runtime_v2.py`
- `autotrader_live_open_v2.py`
- `autotrader_closed_position_reconciliation_v2.py`
- `autotrader_cocktail_mode_1_shadow_v2.py`
- `autotrader_intrabar30_shadow_v2.py`
- `autotrader_risk_control_v2.py`

Recent PRs worth reading for intent and regression rationale:

`#268, #269, #270, #271, #272, #273, #274, #275, #276`.

---

Handoff principle: preserve the hardened Saxo lifecycle, use actual cross-time and direct price evidence to evolve the strategy engine, treat FLAT as a deliberate state, keep shadow evidence separate from profitability claims, and let the eventual architecture grow around the strategy engine that proves useful rather than refactoring toward an imagined endpoint.