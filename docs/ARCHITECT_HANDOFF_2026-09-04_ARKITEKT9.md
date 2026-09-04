# PriceGauger Architecture Handoff — Arkitekt 9 — 2026-09-04

This is the authoritative handoff for Arkitekt 9 after the September 3–4 AutoManager simplification, Strategy Series/Snapshot Spine work, fast-strategy LIVE promotion, MACD baseline expansion, and TradingDesk interaction cleanup.

Always refresh from current `main` before branching. The runtime SHA below is the exact baseline immediately before this documentation-only handoff PR; the docs merge itself will move `main` without changing runtime behavior.

## 1. Exact starting point

Repository: `oveaignerhaukenes-lgtm/PriceGauger`

Runtime `main` at handoff creation:

`f28d70dc1ae9d5e284e2cf4334a2f34adb1829c8`

This is the merge of PR #297, on top of PR #298.

Latest bounded runtime changes:

- #297 — **AutoTrader: fix hybrid re-entry and expose 5m MACD LIVE**
- #298 — **TradingDesk: linked cursor and refined chart gestures**

Final #297 CI: **1137 tests passed**.

Railway production project:

- project: `482dad8f-efc5-415a-b1f7-99f45cb2bd7b` (`grateful-reflection`)
- production env: `9a9b7cc6-1dd0-4044-a0f0-221b06138e8f`
- `pricegauger-web`: `38f57908-1f7a-40ce-9bf4-abcdf43fe429`
- `PriceGauger-stream`: `0be7cd65-533f-4882-9b81-efeda5b35153`
- `PriceGauger-worker`: `5267feed-b5cb-4f85-a24a-0c5124664b59`
- `Postgres`: `a7a66447-8138-4ea9-94b0-5df0c291f337`

At handoff creation, web/stream/worker and Postgres all report `SUCCESS` on the deployment triggered by runtime main `f28d70d...`.

Do not infer the currently selected LIVE strategy from this document. AutoManager now supports hot strategy switching and the user actively tests several strategies. Re-read the active enrollment, exact Saxo position and Product Admission before any execution-related conclusion.

## 2. Product intent and architectural center

PriceGauger is no longer just a fixed MACD bot. The current direction is:

1. observe canonical market state once;
2. persist normalized technical/price/context evidence;
3. let several explicit strategy policies produce auditable `LONG / FLAT / SHORT` targets;
4. compare them continuously on one persisted Strategy Series contract;
5. let one explicitly selected LIVE controller use the hardened execution lifecycle;
6. keep sizing, Product Admission, order authority and Saxo reconciliation outside strategy logic.

The user treats simple MACD policies as controls/baselines, not as the desired final intelligence layer. Strong Cocktail and the later evidence-aggregation/Gin-Tonic direction are closer to the intended end-state, but complexity must earn its place empirically against the simple controls.

Do not do a broad architecture rewrite merely for cleanliness. Continue the gradual migration toward shared persisted evidence/series while the strategy end-state is still being learned.

## 3. Capability boundaries — preserve these

### Position Guardian / RiskControl

Defensive only. It may observe, reduce or close under explicit defensive policy. It must never originate/increase exposure.

### AutoManager

One exact product mandate with one active LIVE controller. It can manage exposure through explicit strategy or user targets, but strategy code never owns Saxo order mechanics.

### AutoTrader

Broader future origination layer inside explicit product/capital/risk mandates. Do not collapse it into Guardian or turn generic UI actions into arbitrary Saxo order paths.

### AI baseline

GPT-5 mini may choose only the strategy target `LONG / SHORT / FLAT` from persisted bounded context. It has no account, sizing, leverage, order-type or Saxo POST authority.

## 4. Current execution invariants — important update from the 2026-09-03 handoff

Preserve:

- no LLM order placement or sizing;
- no strategy-selected leverage;
- exact account + UIC + AssetType + direction Product Admission;
- one active LIVE controller per exact product;
- CLOSE authority and OPEN authority remain separate;
- no one-order reversal;
- reversal remains `CLOSE -> confirmed Saxo FLAT -> OPEN opposite`;
- final Saxo product/account precheck immediately before POST;
- durable execution attempt before POST;
- uncertain submit is never blindly retried;
- stale strategy intent must not revive after a newer user/risk/strategy target;
- no pyramiding or competing working-order race;
- Saxo net direction comes from actual signed/net amounts, not stale `OpeningDirection`.

### Critical lifecycle change from PR #294

The old handoff said authoritative realized-P/L settlement must finish before re-entry. That is no longer the current contract.

Current rule:

- PG CLOSE must have progressed to accepted/reconciled state;
- the exact Saxo product must actually be observed FLAT;
- `SUBMITTING` / uncertain close state still blocks;
- realized-P/L/accounting reconciliation may catch up after the opposite OPEN.

In other words:

`signal/target -> CLOSE -> PG close accepted/reconciled -> exact Saxo FLAT -> OPEN opposite`

while realized P/L settlement is a separate accounting/audit path and is no longer the critical re-entry gate.

Do not casually reintroduce the old P/L-settlement gate. If changing equity/sizing semantics around a just-closed position, inspect the current pilot-equity/accounting contract explicitly so stale accounting cannot silently alter sizing behavior.

## 5. AutoManager Simple Core — current control plane

PR #294 replaced the old confirmation-heavy normal UX with the simpler control model the user actually wants.

Primary controls:

- `BUY` / `SELL`: explicit durable user target through the same AutoManager execution-request lifecycle; web UI never POSTs Saxo orders directly.
- `Manage position`: product-level ON/OFF for automatic strategy authority.
- strategy dropdown: hot-switches the active LIVE strategy instead of attempting to enroll a second controller.
- sizing is secondary/hidden in settings; `All-in` maps to `MAX_WITHIN_PILOT`.

Behavior:

- manual BUY/SELL has precedence over strategy signals until the requested exposure is observed;
- AutoManager OFF pauses automatic strategy signal generation but manual BUY/SELL remains available;
- when management is ON, the exact currently observed Saxo basis is automatically adopted; there is no separate takeover ceremony;
- the legacy panel/read model remains for history/compatibility, not as the intended control plane.

### Hot strategy switching

From #280/#281/#294:

- strategy switch itself sends no Saxo order;
- current `LONG / SHORT / FLAT` exposure may be carried into the new strategy;
- old unstarted requests are superseded;
- real in-flight execution ambiguity blocks switching;
- ordinary unresolved realized-P/L accounting does not block switching;
- Full Auto semantics no longer require a hidden second arming ceremony;
- approval-required mode keeps explicit per-entry approval semantics.

Historical cohort reuse/capital-transfer semantics were intentionally constrained earlier. If touching strategy-cohort resume/reuse, inspect the current ledger implementation first rather than assuming a strategy key can simply reopen an old cohort with arbitrary capital.

## 6. Strategy laboratory and current comparison set

### Persisted baseline controls

Strategy Lab has pure closed-bar MACD 12/26/9 LONG/SHORT controls for:

- 2m
- 5m
- 10m
- 15m
- 20m

All use a common canonical 1m price clock for comparable P/L and start FLAT at the experiment boundary.

### Explicit LIVE simple controls

Current LIVE-capable simple MACD controls include:

- 1m MACD flip — fast runtime
- 2m MACD flip
- 5m MACD flip
- 15m MACD flip
- classic existing 30m strategies remain in the catalog

10m and 20m remain comparison/shadow controls unless explicitly promoted later.

Important identity detail: the 2m/5m/15m strategy keys retain historical `...-shadow-v1` names even though those exact identities are now LIVE-capable. Do not rename them casually: persisted Strategy Series history and LIVE selection intentionally share the same strategy key.

### Pure 5m control — newest addition

PR #297 promotes the already-existing pure 5m Strategy Series control to LIVE. No duplicate model was created.

This is deliberate: the user wants **pure 5m MACD** as a control against the 1m-exit/5m-entry hybrid and more complex models.

`LIVE_MACD_CONTROL_TIMEFRAMES_V1 = (2, 5, 15)`.

## 7. 1m-exit / slower-entry hybrids — corrected semantics

The two hybrid policies are:

- `MACD hybrid · exit 1m / entry 2m`
- `MACD hybrid · exit 1m / entry 5m`

Original #291 semantics were too literal: after a protective 1m exit, FLAT required a brand-new slower-timeframe cross. If the 5m MACD stayed bullish throughout the fast dip, the strategy could remain FLAT indefinitely even after 1m recovered.

PR #297 fixes that in both shadow and LIVE.

Current FLAT entry rule:

- a fresh 2m/5m cross may enter directly; OR
- a fresh 1m recovery cross may re-enter if the latest trustworthy closed slower MACD regime already agrees with that direction;
- no fast re-entry is permitted against the slower regime;
- gaps never invent a transition.

Example:

`LONG -> adverse 1m cross -> FLAT -> 1m crosses bullish again while 5m MACD is still bullish -> LONG`

It no longer waits for an artificial second 5m cross.

Any actual side reversal still uses the shared safe `CLOSE -> Saxo FLAT -> OPEN` execution lifecycle.

Hybrid series version was bumped so persisted comparison history is rematerialized under corrected semantics.

## 8. Strong Cocktail — current fast evidence strategy

Strong Cocktail started as a bounded shadow experiment and is now an explicit LIVE-selectable strategy.

Core idea:

- canonical closed 1m action clock;
- true 1m MACD timing;
- direct price movement/structure/activity qualification;
- persisted 5/10/15/30m Cocktail context;
- slow horizons qualify evidence/confidence instead of acting as sequential gates;
- exposure -> FLAT requires less evidence than FLAT -> opposite exposure;
- WHIPSAW/data-gap safety remains meaningful.

PR #282 fixed a similar stranded-FLAT problem in Strong Cocktail: an adverse fast event could flatten, but the cross was then historical. It now has a continuation-entry path using persistent 1m MACD spread/velocity, 3m price direction, path efficiency, price/structure/activity evidence and slow-context threshold adjustment. It does not require a second formal 1m cross to continue into a strong move.

The simple 1m control was deliberately left unchanged so Strong Cocktail has a clean benchmark.

Do not claim Strong Cocktail has proven positive expectancy. It is a hypothesis being measured against simpler strategies across independent regimes.

## 9. Cocktail Mode #1 and known S&P data-quality issue

The original adaptive Cocktail Mode #1 shadow remains useful as contextual evidence and as the source of forming 5/10/15/30m context for Strong Cocktail.

Known issue still deliberately visible:

`sp500 CFD: invalid 5m ATR`

This is a fail-closed data-quality condition where the supplied 5m path produces zero/invalid ATR. Do not “fix” it by allowing zero ATR or fabricating a minimum value merely to silence logs.

Next correct task is to diagnose S&P instrument/source/canonical-bar construction and determine why 5m true ranges collapse.

## 10. Snapshot Spine and Strategy Series — new persistence architecture

### Feature Snapshot Spine — PR #286

`pg_v2_feature_snapshots` and `pg_v2_feature_values` now provide a versioned persisted technical-state spine.

Principles:

- Technical Core computes once;
- the already-computed object is normalized and persisted, not recalculated independently for storage;
- identity is canonical instrument + observation time + feature set/version;
- long-form feature values use consistent timeframe/feature namespaces;
- formula/semantic changes require a new version, not historical mutation.

Read `docs/SNAPSHOT_SPINE_V1.md` before extending this layer.

### Strategy Series v1 — PR #287 onward

`pg_v2_strategy_series_points` is the common persisted model-equity/target read contract.

It stores:

- raw 1x model equity;
- pilot-equivalent model equity using the current leverage scaling contract;
- explicit strategy/version identity;
- immutable time-series points.

TradingDesk no longer replays historical strategy logic on every render. #288 cut the P/L chart to persisted Strategy Series, and #289 cut AutoManager scorecards to the same persisted read path and isolated AutoManager controls/chart as Streamlit fragments.

Important transitional debt:

- the background materializer still bridges some existing replay functions into Strategy Series;
- native incremental append per model is the desired gradual migration;
- do not reintroduce replay-on-render as a shortcut.

## 11. Pilot-equivalent comparison and AI baseline

### Pilot-equivalent model curves — PR #284

Shadow/model curves are scaled to comparable economic exposure using accepted/reconciled Saxo OPEN precheck notional/budget evidence, with Margin Envelope fallback when necessary.

This changes return scale, not signal timing/state. It intentionally keeps leverage outside strategy policy.

Spread/slippage/transaction-cost modeling is still a separate future layer.

### AI baseline — PR #285

GPT-5 mini receives persisted technical/price/news/context evidence and produces an auditable `LONG / SHORT / FLAT` target with confidence/rationale/context hash.

It is both a Strategy Lab baseline and a LIVE-selectable policy, but the model cannot control sizing or place orders. The dedicated LIVE runtime only converts a persisted target into the ordinary AutoManager request lifecycle.

Do not let AI baseline become a hidden generic execution agent.

## 12. TradingDesk — current interaction/read architecture

Recent UI work is intentionally presentation/read-model heavy, not strategy authority.

### Durable workspace state

Safe DB-backed WorkspaceState persists an explicit allow-list such as selected market, chart timeframe, MACD timeframe, auto-refresh and control-panel width.

Never persist execution authority, one-shot approvals, arming state or strategy activation in generic workspace state.

### Chart performance/read path

- P/L/model chart reads persisted Strategy Series;
- AutoManager scorecards read persisted Strategy Series;
- AutoManager control and comparison surfaces are Streamlit fragments;
- heavy historical replay is absent from ordinary interactive rendering.

### Live chart/UI additions

Recent PRs #292, #295, #296, #298 add:

- right-side bounded/scrollable legend;
- hover trace highlighting;
- compact hover/click information instead of large Plotly bubbles;
- selectable window-anchored VWAP using real positive Saxo volume only;
- persistent AutoTrader entry markers from reconciled LIVE OPEN observations;
- active LONG/SHORT marker label;
- compact ~one-third-size entry triangles after #298;
- forming-candle lightweight overlay;
- pinch = X zoom;
- horizontal two-finger motion = X pan;
- vertical two-finger motion inside the plot = Y-price scale around pointer;
- wheel gestures are captured only inside the actual plot rectangle so page scrolling remains normal outside it;
- linked vertical time cursor across Live/indicator stack and AutoManager comparison chart.

These browser-local interactions need continued real-browser testing; CI verifies contracts/source behavior but cannot prove every trackpad/browser nuance.

## 13. Runtime observability/repair cleanup

PR #283 established several useful operational conventions:

- legacy paper benchmark uses exact persisted anchor identity rather than a ±5 minute enrollment timestamp heuristic;
- fast LIVE logs emit causal observed -> desired -> pending/request state changes and deduplicate repeated polls;
- product-specific Saxo stale-repair 401/403 failures back off for 30 minutes instead of spamming full tracebacks;
- unexpected errors still retain useful traceback visibility.

Natural Gas 403 backoff was observed working in production after deployment.

Do not suppress real data-quality failures such as the S&P invalid ATR merely to make logs quiet.

## 14. Saxo direction and position identity

Continue to treat Saxo intraday netting carefully.

Do not use stale `OpeningDirection` as net truth. Resolve direction from actual `AmountLong`, `AmountShort` and signed `Amount`, fail closed on material ambiguity, and keep exact account/UIC/AssetType identity throughout execution/audit.

A currently observed manual Saxo basis can be auto-adopted by AutoManager when management is ON, but that does not relax Product Admission or order safety.

## 15. Futures rollover remains an unbuilt architectural capability

No dedicated ContractLifecycle/Rollover engine exists yet.

Required principle remains:

- stable economic-market identity above;
- immutable concrete futures contract/UIC execution identity within each contract epoch;
- never silently mutate a LIVE controller from old UIC to new UIC;
- close old contract safely, reconcile/observe FLAT, then optionally open the new admitted contract;
- roll gaps must never masquerade as strategy return, MACD cross or shock.

Build this before autonomous management of expiring futures becomes important.

## 16. What Arkitekt 9 should do first

Recommended sequence:

1. **Refresh production truth first.** Read current `main`, active LIVE enrollment, Saxo exact position, recent execution requests and Railway logs. Strategy selection changes frequently during testing.
2. **Observe the next natural OPEN/reversal end-to-end.** The user’s recent concrete failure mode was strategies closing positions but not opening new ones. Verify `signal/target -> request -> CLOSE if needed -> observed FLAT -> OPEN -> reconciled marker` without manual rescue.
3. **Compare pure 5m against the 1m-exit/5m-entry hybrid.** This is an explicit control experiment requested by the user. Do not blur the two strategy identities or semantics.
4. **Watch corrected hybrid re-entry.** Specifically confirm a fast exit followed by 1m recovery while the slower regime remains aligned produces re-entry without needing a second slow cross.
5. **Continue Strong Cocktail vs simple controls across regimes.** Complexity must beat 1m/2m/5m/15m controls on enough independent episodes before further promotion/refinement.
6. **Diagnose `sp500 CFD invalid 5m ATR` as a source/bar-quality problem.** Do not weaken ATR validity rules.
7. **Continue native incremental Strategy Series migration** where it materially reduces replay/materializer debt; never move historical replay back into TradingDesk rendering.
8. **Only then refine the evidence engine** with explicit regime/impulse/price-confirmation and momentum-price divergence if the collected comparison indicates it is useful.
9. Keep futures ContractLifecycle/Rollover on the architectural roadmap.

## 17. Strategy-development principle from the user

The intended analytical model is not “find the perfect indicator”. The desired decomposition is roughly:

- regime;
- momentum/impulse;
- price structure/confirmation;
- volatility/activity;
- then secondary/contextual evidence.

Indicators are evidence, not truth. Technical levels may also be reflexive/behavioral because enough market participants believe and act on them, so they are still useful for timing/pressure/structure even when they are not treated as deep causal laws.

For future Cocktail/Gin-Tonic work, preserve this distinction:

`MACD state != price confirmation != execution authority`.

## 18. Key files to orient from

Execution/control:

- `autotrader_automanage_dispatch_v2.py`
- `autotrader_fast_live_runtime_v2.py`
- `autotrader_macd_hybrid_v1.py`
- `autotrader_macd_timeframe_live_v1.py`
- `autotrader_strategy_catalog_v2.py`
- `autotrader_manual_target_v2.py`
- `autotrader_manage_control_v1.py`

Strategy/evidence:

- `autotrader_strong_cocktail_shadow_v2.py`
- `autotrader_cocktail_mode_1_shadow_v2.py`
- `autotrader_macd_timeframe_controls_v1.py`
- `autotrader_ai_shadow_v1.py`
- `autotrader_ai_live_runtime_v1.py`

Persistence/read model:

- `feature_snapshot_spine_v1.py` / Snapshot Spine-related modules
- `autotrader_strategy_series_v1.py`
- `autotrader_strategy_series_materializer_v1.py`
- `autotrader_pnl_chart_v2.py`

TradingDesk:

- `trading_desk_v2.py`
- `trading_desk_live_overlay_v2.py`
- `trading_desk_legend_hover_v1.py`
- WorkspaceState modules introduced around #275/#276

Documentation:

- `docs/SNAPSHOT_SPINE_V1.md`
- `docs/COCKTAIL_MODE_1_V1.md`
- this handoff

## 19. Working discipline

The project has benefited from bounded capabilities and explicit verification. Continue that:

- refresh `main` before every branch;
- one coherent branch/PR per capability;
- inspect the diff, not only tests;
- green full CI before merge;
- merge with expected-head guard when available;
- verify Railway web/stream/worker after runtime merges;
- use production logs/data to distinguish strategy bugs, stale feed/data-quality bugs, UI/read-model bugs and actual execution lifecycle bugs;
- never “fix” an execution/data issue by weakening a safety invariant simply to make the UI/logs look healthy.

The most important near-term objective is empirical: make the control strategies, hybrids and Strong Cocktail produce trustworthy comparable histories while the real LIVE lifecycle repeatedly proves it can close and re-open autonomously without getting stranded FLAT.
