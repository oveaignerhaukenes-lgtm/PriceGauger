# PriceGauger Architecture Handoff — Arkitekt 10 — 2026-09-07

This is the authoritative Arkitekt 9 → Arkitekt 10 handoff after the September 4–7 TradingDesk chart migration, Strategy Lab/Spring presentation work, futures rollover implementation, and the market-reopen execution-safety incident/hardening.

Always refresh from current `main` before branching. The runtime SHA below is the exact baseline immediately before this documentation-only handoff branch; merging this documentation will move `main` without changing runtime behavior.

---

## 1. Exact starting point

Repository:

`oveaignerhaukenes-lgtm/PriceGauger`

Authoritative runtime `main` at handoff creation:

`07a464cc0fd57cfdb086270e8d8d83240d61a567`

That commit is:

**PR #322 — AutoTrader: quarantine stale broker orders and late fills**

Final #322 CI:

**1215 tests passed**

Railway production project:

- project: `482dad8f-efc5-415a-b1f7-99f45cb2bd7b` (`grateful-reflection`)
- production env: `9a9b7cc6-1dd0-4044-a0f0-221b06138e8f`
- `pricegauger-web`: `38f57908-1f7a-40ce-9bf4-abcdf43fe429`
- `PriceGauger-stream`: `0be7cd65-533f-4882-9b81-efeda5b35153`
- `PriceGauger-worker`: `5267feed-b5cb-4f85-a24a-0c5124664b59`
- `Postgres`: `a7a66447-8138-4ea9-94b0-5df0c291f337`
- `Spring-Trade-Engine`: `254b205b-1633-4c69-aa84-486a0fa6f052`

At handoff creation all five production services above report `SUCCESS` on/after the #322 deployment.

### Important open PR

**PR #321 — `Strategy Lab: explicit Spring observation pane and wrapped legend` is still OPEN and is NOT in `main`.**

It was green before `main` advanced, but its base predates #322 and GitHub currently does not report it mergeable. Do not assume its presentation changes are deployed. Rebase/recreate its small renderer-only patch against fresh `main` before merging.

#321 contains only presentation changes:

- legend wraps to additional rows instead of horizontal scrolling;
- Spring is explicitly labeled `Spring · blind observasjon` inside its existing pane;
- Spring legend entries are grouped together;
- only already-existing factors are shown: displacement, shock z, energy proxy and turning points;
- no Spring strategy semantics, execution, sizing or persistence changes.

---

## 2. Product center — preserve this architecture

PriceGauger's current architectural center is:

1. observe canonical market state once;
2. persist normalized technical/price/context evidence;
3. let explicit strategies produce auditable `LONG / FLAT / SHORT` targets;
4. compare strategies continuously through one persisted Strategy Series contract;
5. let exactly one explicitly selected LIVE controller per exact product use the hardened execution lifecycle;
6. keep sizing, leverage authority, Product Admission, Saxo order mechanics and reconciliation outside strategy logic.

Simple MACD policies are controls/baselines, not the desired final intelligence layer. Strong Cocktail, AI and Spring-derived ideas must earn complexity empirically against those simple controls.

Do not do a broad rewrite merely for architectural tidiness. The current project is deliberately converging through bounded capabilities and persisted contracts while the strategy end-state is still being learned.

---

## 3. Execution invariants — non-negotiable

Preserve all of these unless there is an explicit architecture decision with tests and production verification:

- no LLM order placement or sizing;
- no strategy-selected leverage;
- exact account + UIC + AssetType + direction Product Admission;
- one active LIVE controller per exact product;
- defensive RiskControl/Position Guardian may reduce/close but never originate/increase exposure;
- CLOSE authority and OPEN authority are separate;
- no one-order reversal;
- reversal remains `CLOSE -> exact Saxo FLAT -> OPEN opposite`;
- final Saxo product/account/margin precheck immediately before POST;
- durable execution attempt before POST;
- uncertain submit is never blindly retried;
- stale intent cannot revive after newer user/risk/strategy authority;
- no pyramiding or competing working-order race;
- Saxo net direction comes from actual long/short/net amounts, never stale `OpeningDirection` alone;
- generic UI/workspace persistence must never carry execution authority, arming, approval or strategy activation.

### Current close → re-entry rule

Do **not** restore the old rule that realized-P/L accounting must finish before opposite re-entry.

Current lifecycle is:

`target -> CLOSE -> PG close accepted/reconciled -> exact Saxo product observed FLAT -> OPEN opposite`

`SUBMITTING` / uncertain close still blocks. Realized P/L settlement may catch up separately as accounting/audit.

---

## 4. Critical production incident: unexpected SHORT at Sunday reopen

This is the most important new execution context for Arkitekt 10.

### What the user observed

At exactly ~00:00 Norway time on Sunday/Monday market reopen, AutoTrader appeared to put on a SHORT. Price then jumped sharply upward and the position lost almost 1%. The active MACD strategy did not flatten on the apparent cross in the first minutes. The user manually changed the position and re-enabled management.

The user explicitly noted that this class of failure would be unacceptable if AutoTrader were managing ~1M NOK.

### Production evidence

Railway logs showed:

- `23:59:50` local vicinity: RiskControl saw 0 positions;
- `00:00:00`: still 0 positions;
- around `00:00:06`: active AutoManage strategy could **not** evaluate because it lacked enough fresh canonical 1m history for MACD 12/26/9 after reopen;
- by `00:00:10`: RiskControl suddenly saw one Saxo position.

Therefore the new SHORT appeared while the active strategy itself was not capable of generating a fresh decision.

Further historical logs from Friday showed the same active pilot had persisted SHORT transition authority while observed exposure was FLAT, including repeated `TARGET_SHORT` / `PENDING_TRANSITION_CONTINUED` state before the weekend session boundary.

After the user's manual intervention, Saxo net-position data showed a mixed basis (`AmountLong=0.05`, `AmountShort=0.01`, net +0.04, stale `OpeningDirection=Sell`), strongly consistent with a residual 0.01 SHORT leg having existed.

We did not obtain a historical broker OrderId/ExternalReference proving the exact original Saxo order beyond doubt, but the evidence is strong enough that the architecture must treat it as a stale/broker-side working-order / late-fill provenance failure rather than a normal strategy decision.

### Root architectural weakness found

Before #322:

- a broker-side working order could exist independently of current fresh strategy authority;
- the executor would notice that an order existed and avoid creating a competing one, but did not own a complete stale-working-order cleanup/provenance lifecycle;
- AutoManager could silently auto-adopt a newly observed exact Saxo position into managed state before proving where that position came from;
- market-session reopen and strategy warmup were not strong enough provenance boundaries.

This combination is unsafe at serious capital scale.

---

## 5. PR #322 — stale working-order and late-fill guard

#322 is now the execution-safety baseline and should be read before changing LIVE OPEN or AutoManager adoption.

Primary capability lives around the new execution guard and the hardened LIVE OPEN facade.

### New principles

1. **No new OPEN unless Saxo explicitly reports the exact market open immediately before durable OPEN attempt creation.**
2. **Working orders are continuously inspected.**
3. Only PG-owned OPEN orders with `ExternalReference` prefix `pg-open-*` may be auto-cancelled.
4. `pg-close-*` remains owned by the existing CLOSE lifecycle and is not casually cancelled by the OPEN guard.
5. A manual/foreign/unknown Saxo working order is **never auto-cancelled**. Instead AutoManager on that exact product is paused so PG cannot compete with it.
6. A stale PG OPEN working order whose request/strategy/session authority is no longer current is cancelled by exact broker OrderId + AccountKey and audited.
7. Accepted OPEN attempts whose authority expires before reconciliation are quarantined.
8. An unexpected late fill is not silently treated as a valid strategy position merely because it matches account/UIC/AssetType.
9. Execution anomalies are persisted for later TradingDesk monitoring.
10. Successful broker OPEN acceptance now logs request/order provenance including ExternalReference/OrderId/UIC/side/amount.

### Important failure mode

If provenance cannot be verified, fail closed on **new OPEN authority**, not by deleting arbitrary Saxo state.

Unknown/manual orders are left untouched. This is deliberate.

### New/important persistence

`pg_v2_autotrader_execution_anomalies`

Use this as the future read-model source for an AutoTrader monitor/status UI rather than reconstructing anomalies from logs.

### First thing Arkitekt 10 should verify

Inspect production after #322 for:

- guard startup/runtime logs;
- any active execution anomalies;
- any current Saxo working orders on managed products;
- exact current Saxo net position;
- current active LIVE enrollment and `auto_manage_enabled` state.

Do not infer current position or strategy from this handoff; the user actively changes them.

---

## 6. AutoManager Simple Core — current semantics

The normal TradingDesk control plane remains intentionally simple:

- `BUY` / `SELL` = explicit durable user target through the existing AutoManager execution-request lifecycle;
- UI never POSTs directly to Saxo;
- `Manage position` controls automatic strategy authority for the product;
- strategy dropdown hot-switches the active LIVE strategy rather than enrolling a second controller;
- sizing remains secondary/optional; `All-in` maps to the existing bounded maximum-within-pilot sizing policy.

Manual BUY/SELL should continue to use the same safe request lifecycle, Product Admission, sizing and final Saxo prechecks as strategy-originated targets.

### Auto-adoption rule changed conceptually by #322

The old UX principle was “when management is ON, simply adopt the exact observed Saxo position.” That is no longer sufficient for arbitrary newly appearing positions.

A position that appears from unresolved broker provenance must be quarantined/paused rather than silently legitimized.

Do not reintroduce unconditional background adoption as a convenience shortcut.

---

## 7. User-approved next AutoManager/TradingDesk monitor design

This was discussed immediately before handoff and the user explicitly confirmed the interpretation.

### A. Small BUY / SELL controls inside the LIVE chart

Place compact buttons **inside the LIVE chart, upper-left**.

Requested visual semantics:

- small **red `BUY`** button;
- small **blue `SELL`** button;
- each should show the current executable quote, e.g. `BUY 74.26` / `SELL 74.23`, so the spread is visible at a glance.

These buttons must do **exactly the same thing** as the existing BUY/SELL controls in AutoManager:

`chart button -> request_manual_target_v2() -> existing execution-request lifecycle`

They are not a second execution implementation and must never POST Saxo directly from browser/UI code.

### B. AutoManager status button, bottom-right

Separate from BUY/SELL.

User wants a persistent status button near the lower-right of TradingDesk/chart area:

- when actively managed/live: **`Armed LIVE`**;
- when not live/managed: green **`AutoManage OFF`**.

The exact color design can be refined, but the state semantics must remain unambiguous.

### C. Clicking the status button opens a monitor panel

Panel should expose:

- exact current position/direction/amount;
- current and/or realized P/L development;
- selected AutoManager strategy;
- current execution/anomaly/provenance state;
- a small AutoTrader diagnostic chart showing the strategy's underlying logic.

For MACD strategies the small diagnostic chart should make it visually obvious:

- MACD vs signal;
- current spread/distance to cross;
- which direction/action a cross would imply;
- ideally how close the strategy is to its next actionable transition.

Do not invent a generic “distance to action” metric for strategies where it is not semantically defined. The monitor should be strategy-aware.

### D. User-approved control semantics

The user confirmed this exact interpretation:

- **Pause**: go FLAT, then keep the controller/strategy identity paused. `Start` later continues the same management path from FLAT.
- **Start**: resume the paused AutoManager strategy/controller.
- **Stop**: end AutoManager management/strategy authority **without automatically closing** an existing position.
- **Close position**: stop AutoManager **and** close the position.

Implementation warning: `Pause` should be modeled as an explicit durable `FLAT` target followed by paused strategy authority, not as “toggle management OFF while a close might be in flight.” The sequence needs to be deterministic and auditable.

Likewise `Close position` should compose existing STOP + defensive/explicit CLOSE capability; do not create a UI-only direct Saxo close route.

---

## 8. TradingDesk chart architecture — Lightweight Charts is now canonical

The LIVE TradingDesk chart was successfully cut from Plotly to **TradingView Lightweight Charts 5.2.1**.

Key cutover:

**PR #312 — direct LIVE engine cutover**

Main direct runtime paths include:

- `tradingdesk_ui/charts/lightweight/direct_runtime.py`
- `tradingdesk_ui/charts/lightweight/direct_contract.py`
- `tradingdesk_ui/charts/lightweight/live_update.py`

The direct chart builds from canonical PG bars/Technical Core/overlays/markers rather than building a Plotly figure and bridging it.

### Current user-tested chart behavior

The user physically tested on Android and confirmed the following now work:

- compact one-line timeframe selectors;
- native/mapped touch scaling of the main Y price axis;
- Y scaling on indicator panes;
- X-axis/timeline scaling by touch;
- pan/pinch navigation;
- internal pane resizing;
- total chart-height resizing independently of pane ratios;
- persistence of chart choices/geometry across reloads;
- forming candle updates;
- execution/trade markers;
- responsive mobile layout.

Trade marker colors were changed away from candle red/green:

- LONG: sky blue `#0ea5e9`
- SHORT: amber `#f59e0b`

The user considered the chart foundation essentially finished after these interactions.

### Important geometry model

Keep two independent concepts:

1. pane separators adjust **relative pane proportions**;
2. bottom/global handle adjusts **total chart container height** while preserving relative pane proportions.

Do not collapse these back into one behavior.

### Timeframe toolbar

Use the compact segmented one-line control (`1m 2m 5m 10m 15m 30m`) with no mobile stacking.

The previous separate “MACD · 5 min” UI control was intentionally removed as redundant; indicator timeframe follows the chart selection/current configured chart logic rather than displaying a duplicate top-level control.

---

## 9. Strategy Lab / P&L charts also use Lightweight Charts

PR #317 migrated the P/L / model comparison surface away from Plotly as well.

Current goals achieved:

- no Plotly modebar covering legends;
- native Lightweight pan/zoom;
- shared temporal comparison;
- compact range controls;
- legend under chart;
- persisted Strategy Series remains the read contract; no replay-on-render.

PR #318 then split comparison into clearer semantic groups.

### Benchmark / controls

Contains:

- a thin market-reference curve above the strategy curves;
- LIVE realized P/L;
- simple MACD/control strategies.

Market reference is read-only canonical price context, normalized as percent from the visible/start comparison boundary so regimes and strategy P/L can be visually compared.

### Advanced / experimental

Contains:

- the same market-reference context;
- Strong Cocktail / AI / adaptive/non-control strategy series;
- Spring observation data.

Spring energy is visible by default in current `main`.

The design intent is important:

- Benchmark answers **“does the complex thing beat something simple?”**
- Advanced answers **“how do the more adaptive/experimental models differ, and under what market regimes?”**

Do not let Benchmark become a dumping ground for every new model.

### Pending #321 presentation cleanup

As noted above, the explicit Spring pane label and wrapped legend are not yet merged. Reapply/rebase that renderer-only patch against current `main`.

---

## 10. Spring Trade Engine — current scientific boundary

Spring remains deliberately **shadow/observation-first**.

The hypothesis is:

> Can a blind model, seeing only price evolution, identify post-shock periods behaving more like a damped oscillator than random noise/trend?

Do not bake the desired answer into the observer.

PR #302 established the evaluation spine with persisted primitives/outcomes including:

- `SpringTurningPointV1`
- `SpringEpisodeCandidateV1`
- `SpringForwardLabelV1`
- `SpringRuntimeCoverageV1`

Tables include:

- `pg_v2_spring_turning_points`
- `pg_v2_spring_episode_candidates`
- `pg_v2_spring_forward_labels`
- `pg_v2_spring_runtime_coverage`

Evaluation contract includes forward labels at 5/15/30/60/120 minutes and baseline linkage through Strategy Series.

### Current factors actually available for presentation

Do not invent names/semantics merely because they fit the physical metaphor.

Currently legitimate observable Spring presentation factors are:

- displacement;
- shock z;
- energy proxy;
- turning points.

The user is interested in eventual factors such as “absorption” and “dampening”, but those must first be mathematically defined, persisted and validated. Do not label an existing proxy as absorption/damping without an explicit semantic/versioned contract.

### User preference

The user is especially interested in watching **Spring energy** evolve; keep it visible by default.

---

## 11. Futures rollover is now implemented — data identity only

The old handoff said rollover was unbuilt. That is no longer true.

### PR #319 — generic monitored-futures rollover

Confirmed production issue before #319:

- old Brent UIC `43660942` had stopped producing real data;
- Saxo reported `NoMarket` and bars stopped at 2026-08-28.

#319 introduced a generic monitored-futures resolver that:

- checks subscribed Saxo `ContractFutures` / `CfdOnFutures` sources;
- prefers Saxo `PrimaryListing` as broker-provided next/front active contract identity;
- creates/reuses a new immutable v2 instrument identity;
- disables collection on the old contract and enables it on the new one;
- seeds history for the new exact contract through existing runtime;
- persists rollover audit events;
- lets TradingDesk show a red vertical `ROLLOVER · old → new` marker on the first new-contract bar.

Critically, rollover does **not** mutate a LIVE AutoManager/AutoTrader controller from old UIC to new UIC.

Stable economic-market identity may continue above immutable contract identities, but execution identity remains exact.

### Production rollover observed

Brent:

`43660942 -> 44297299`

Silver:

`45184335 -> 46652614`

The new Brent stream was accepted and produced live chart data on UIC `44297299`.

### PR #320 — audit/schema/transaction hardening

Initial production rollout exposed a partial-boundary bug: collection changed contracts before the rollover audit table existed, so the data switch happened but the audit event initially failed.

#320 fixed that by:

- ensuring `pg_v2_instrument_rollovers` exists before automatic rollover;
- idempotently recovering missing audit rows from persisted rollover metadata;
- making old-subscription disable + new-subscription enable + audit insert one DB transaction;
- rolling back collection switch if audit cannot commit;
- rejecting same-immutable-identity nonsense transitions;
- keeping rollover failure bounded so a schema problem disables rollover capability rather than killing all realtime feeds.

Production recovery successfully reconstructed audit events for both Brent and Silver, so chart rollover markers have persisted evidence.

### Remaining futures issue: Natural Gas

Natural Gas UIC `50419383` was also detected as rollover-eligible/invalid, but Saxo did not provide a safely resolvable next contract through the current PrimaryListing path.

PriceGauger correctly **did not guess**.

Next futures work should add a generic Saxo-based discovery fallback for cases where the old UIC is already too stale/invalid to expose a usable PrimaryListing.

Requirements for that fallback:

- resolve candidate contracts from broker-supported instrument discovery, not hard-coded month symbols;
- select the broker/front/commonly active contract using explicit metadata/liquidity evidence;
- preserve immutable UIC instrument epochs;
- never silently mutate LIVE execution identity;
- preserve rollover audit + red chart boundary marker;
- fail closed if the candidate cannot be proved safe.

This is important, but execution-safety verification after #322 is higher priority.

---

## 12. Strategy matrix / controls to preserve

Simple MACD controls remain essential benchmarks.

Persisted closed-bar 12/26/9 baseline controls include 2m, 5m, 10m, 15m, 20m using canonical 1m price clock and common Strategy Series comparison.

LIVE simple controls include:

- fast 1m;
- 2m;
- 5m;
- 15m;
- classic 30m strategies.

10m and 20m remain comparison/shadow unless explicitly promoted.

Historical strategy keys for 2m/5m/15m still contain `...-shadow-v1` naming even though they are LIVE-capable. Do not rename casually because persisted history and LIVE identity intentionally share those keys.

### Hybrids

`1m exit / 2m entry` and `1m exit / 5m entry` include recovery logic so a fast 1m recovery can re-enter when the latest trustworthy slower MACD regime is already aligned. They no longer require an artificial second slow cross.

No fast entry may occur against the slower regime.

### Strong Cocktail

Strong Cocktail remains a LIVE-selectable adaptive strategy using 1m action timing plus price/structure/activity evidence and slower context as evidence/confidence rather than sequential hard gates.

Do not claim it has positive expectancy yet; keep comparing against simple controls across independent regimes.

### AI baseline

GPT-5 mini may produce only persisted `LONG / SHORT / FLAT` strategy targets from bounded context. It has no sizing, leverage, order-type or direct Saxo POST authority.

---

## 13. Snapshot Spine and Strategy Series remain canonical persistence contracts

### Feature Snapshot Spine

Read `docs/SNAPSHOT_SPINE_V1.md` before extending.

Core tables:

- `pg_v2_feature_snapshots`
- `pg_v2_feature_values`

Technical Core computes once; persist the already-computed normalized object. Semantic/formula changes require explicit versioning rather than historical mutation.

### Strategy Series

Core table:

`pg_v2_strategy_series_points`

This is the common persisted model-equity/target read contract for TradingDesk/Strategy Lab.

TradingDesk must not regress to replaying strategy history on every render.

Transitional replay→materializer bridges may still exist; continue gradual native incremental append when useful rather than creating a second series architecture.

---

## 14. TradingDesk workspace state safety

Safe presentation/workspace persistence may store explicit UI allow-list state such as:

- selected market;
- chart timeframe/window;
- overlay/indicator choices;
- chart total height;
- pane proportions;
- presentation preferences.

Never use generic workspace state for:

- execution arming;
- one-shot approvals;
- active strategy authority;
- Product Admission;
- sizing authority;
- Saxo order state.

The recent chart work intentionally keeps local/browser geometry state separate from execution control.

---

## 15. Known data-quality issue: S&P 5m ATR

Known existing failure remains:

`sp500 CFD: invalid 5m ATR`

The supplied/canonical 5m path collapses ATR to invalid/zero in some cases.

Do not silence this by permitting zero ATR or fabricating a minimum ATR.

Correct work is to inspect instrument/source/canonical-bar construction and determine why true range collapses.

---

## 16. Important code areas to read before changing behavior

Execution / AutoManager:

- `autotrader_live_open_v2.py`
- `autotrader_live_open_legacy_v2.py`
- `autotrader_execution_guard_v1.py` (new #322 capability; inspect current path/name on `main`)
- `autotrader_live_close_v1.py`
- `autotrader_manage_control_v1.py`
- `autotrader_manual_target_v2.py`
- `autotrader_managed_positions_v1.py`
- `autotrader_strategy_enrollment_v2.py`
- `autotrader_strategy_switch_v2.py`
- `autotrader_strategy_switch_provenance_v2.py`
- `autotrader_risk_control_v2.py`
- `tradingdesk_automanager_simple_v1.py`

TradingDesk / charts:

- `pages/0_TradingDesk.py`
- `tradingdesk_ui/charts/lightweight/`
- Strategy Lab Lightweight renderer/runtime files under the same bounded presentation context
- `docs/TRADINGDESK_UI_ARCHITECTURE_V1.md`

Persistence/evidence:

- `docs/SNAPSHOT_SPINE_V1.md`
- Strategy Series persistence/materializer modules
- Spring evaluation/read-model modules

Futures:

- current futures rollover resolver/audit modules introduced in #319/#320
- canonical collection subscription/instrument identity code

Always inspect fresh names from `main`; do not rely on this list as exhaustive.

---

## 17. Recommended Arkitekt 10 work sequence

### Priority 0 — verify #322 against production truth

Before adding new execution-facing UI:

1. read current active LIVE enrollment(s);
2. read exact Saxo positions and working orders;
3. inspect `pg_v2_autotrader_execution_anomalies`;
4. inspect #322 guard logs after deployment;
5. verify no stale `pg-open-*` order remains;
6. verify unknown/manual working-order handling pauses instead of cancels;
7. verify a late/unresolved position cannot be silently adopted.

If an anomaly is active, diagnose that before adding more execution controls.

### Priority 1 — resolve PR #321 cleanly

Rebase/recreate its presentation-only Spring changes on current #322 `main`, rerun CI and merge if still clean.

Do not resolve a conflict by touching strategy/execution semantics; #321 should remain renderer-only.

### Priority 2 — build AutoTrader monitor/status UI

Implement the user-approved `Armed LIVE` / `AutoManage OFF` status control and monitor panel using existing read models + persisted execution anomalies.

Then add small chart BUY/SELL quote buttons that route to the existing manual-target lifecycle.

Do not create a browser-side order API.

### Priority 3 — Natural Gas / generic futures discovery fallback

Extend rollover discovery for invalid old UICs without hard-coded symbols or execution UIC mutation.

### Priority 4 — continue Spring observation, not hypothesis fitting

Collect episodes/outcomes and compare against controls. Define any future “damping/absorption” features explicitly and version them before UI naming.

### Priority 5 — S&P ATR data-quality diagnosis

Fix source/canonical bars, not the validity gate.

---

## 18. Product/UX direction from the user

The user increasingly wants PriceGauger to behave like a professional trading workstation rather than a collection of Streamlit widgets.

Recent decisions that tested well:

- direct Lightweight chart interaction rather than Plotly toolbars;
- compact controls embedded close to the chart;
- visible broker/strategy provenance and causal state;
- market-reference line next to strategy P/L to identify regime shifts;
- baseline vs advanced strategy separation;
- Spring factors visible as scientific observation rather than hidden in logs;
- rollover visible in the chart as an explicit event;
- execution state should be monitorable, not merely “armed somewhere in settings”.

The next AutoTrader monitor is therefore not just cosmetic. It should answer, at a glance:

- What position does Saxo actually have?
- Who/what has authority over it?
- Is AutoManager live, paused, stopped or anomalous?
- What strategy is selected?
- What is the strategy currently seeing?
- How close is it to an actionable transition?
- Is any broker working order outstanding?
- Is there any unresolved execution provenance?

This observability is part of the safety model, especially if capital grows substantially.

---

## 19. Final handoff warning

Do not treat “Saxo position exists” as sufficient proof that AutoManager should manage it.

The September 7 reopen incident demonstrated the difference between:

**exposure state** and **execution provenance**.

At serious capital scale, PriceGauger must know not only `LONG / SHORT / FLAT`, but whether that state came from a still-authorized PG request, a manual user action, an unresolved working order, a late broker fill, or an uncertain execution attempt.

#322 is the first explicit guard around that distinction. Preserve and deepen it.

Likewise, futures rollover must remain a **market-data/contract-lifecycle capability** unless and until a separate explicit execution migration policy is designed. Never let “front contract changed” silently become “LIVE position/controller changed UIC”.

---

## 20. One-sentence orientation for Arkitekt 10

**PriceGauger now has a strong professional chart/read foundation, persisted strategy/Spring comparison and automatic data-contract rollover; the next architectural priority is to make LIVE execution provenance and AutoManager state visibly monitorable while preserving the new fail-closed working-order/late-fill guard introduced after the real market-reopen incident.**
