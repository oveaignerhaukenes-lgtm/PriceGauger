# PriceGauger — Next Architect Handoff

Updated: 2026-08-31

This is the operative handoff for the next architecture/development thread. Read this first, then `docs/CURRENT_STATUS.md` for the stable baseline and historical rationale.

## 1. Authoritative starting point

Repository: `oveaignerhaukenes-lgtm/PriceGauger`

Canonical `main` at handoff creation:

`787f9b8292f4e26065070b34b191acd2d2696f0a`

This is the merge of PR #249: **AutoManager: explicit sizing modes and LIVE armed indicator**.

Production Railway status at handoff creation:

- `pricegauger-web`: SUCCESS
- `PriceGauger-stream`: SUCCESS
- `PriceGauger-worker`: SUCCESS
- `Postgres`: SUCCESS

Do not start from an older handoff SHA. Always refresh from `main` before new work.

## 2. Immediate product objective

The immediate goal is deliberately narrow: prove that the technical execution chain works with a tiny isolated LIVE pilot.

The intended LIVE test is:

- exact product: canonical `US Tech 100 NAS · Saxo 4912`
- Saxo identity: `UIC 4912`, `AssetType=CfdOnIndex`
- LIVE strategy: `macd-30m-long-flat-v1`
- signal basis: fully closed canonical 30m bars, MACD 12/26/9
- desired LIVE behavior: `LONG → EXIT/FLAT on bearish MACD cross → RE-ENTRY LONG on next bullish MACD cross`
- entry mode for this test: `AUTO` / Full auto, because Manage-only cannot re-enter
- SHADOW comparison: long/short flip (`macd-30m-long-short-v1`, presented in current UI as MACD Switch)
- desired SHADOW behavior: `LONG → SHORT on bearish cross → LONG on bullish cross`

LIVE and SHADOW must use the same canonical bar path and aligned starting basis. Shadow must never receive order authority or contaminate authoritative Saxo P/L.

Do not add macro/context/LLM input to this strategy test. This first pilot is only a technical proof of deterministic MACD signal → execution/reconciliation → re-entry.

## 3. Capability boundaries — keep these names distinct

The naming finally settled into three different capability classes. Preserve this separation.

### Position Guardian

Defensive engine. Intended authority is asymmetric:

- observe positions regardless of who opened them
- may eventually reduce or close exposure under hard risk/anomaly conditions
- must not create or increase exposure
- later candidate inputs: regime detector, volatility shock, correlation break, severe anomaly
- may later tell AutoTrader to re-evaluate, but should not itself create risk

Do not build the advanced Guardian batch now unless explicitly requested. Current RiskControl is the seed of this concept, but a formal Guardian architecture should be a later controlled batch.

### AutoManager

Manages one explicitly selected position/product mandate.

For the current long/flat LIVE test it is allowed to:

- manage the existing LONG
- exit to FLAT on strategy signal
- re-enter LONG on a later valid signal when entry mode is AUTO

This is broader than “close-only management”. Manage-only is merely one entry-authority mode inside AutoManager.

### AutoTrader

Future broader autonomous trading layer:

- may originate exposure without a user-created starting position
- can eventually choose among approved markets/opportunities/strategies inside explicit capital and risk mandates
- must still pass Product Admission, Margin Envelope and execution gates

Do not collapse Position Guardian, AutoManager and AutoTrader back into one ambiguous concept.

## 4. Recent important merges

### #243 — Context v2 / Overview consistency

Fixed two misleading UI/semantic issues:

- responsive Overview could visually place one market's forecast graph immediately above the next market header, making ownership ambiguous
- Context v2 adapter inherited legacy Telegram normalized-score semantics where one weak same-direction event could look like ±1.00

Now Context uses bounded directional pressure and confidence-aware `UNCERTAIN` presentation. `TA-only v1` user-facing wording was also clarified as recipe version 1 on v2, not legacy Technical v1.

### #244 — retire legacy Telegram semantic runtime hook

`TelegramFlowStore.save_snapshot()` no longer has a dormant default path that can invoke the retired Information State → Decision State → Recommendation runtime. Explicit attempts to invoke that old semantic pipeline fail fast.

### #246 — TradingDesk main-pane AutoManager + forecast axes

- AutoManager moved out of the sidebar/right control column into the wide main pane
- old manual SIM “Handel” surface removed from TradingDesk
- canonical market selection survives reruns
- explicit LIVE vs SHADOW enrollment selection
- default comparison for long/flat LIVE is flip/MACD Switch SHADOW
- LIVE/SHADOW scorecards side by side
- forecast graphs now show compact time ticks and right-side price ticks

### #247 — Saxo closed-position response normalization

Saxo `port/v1/closedpositions` may return a bare JSON list even on HTTP 200. Only that exact endpoint is normalized to the existing `{Data: [...]}` collection contract. Other endpoints remain strict.

This restored authoritative closed-position / realized-P&L reconciliation.

### #248 — generalized account-specific fractional Saxo sizing

This is important. Do not reintroduce the old bug.

The old code incorrectly treated `DefaultAmount=1` as minimum order size for the index CFD, producing a bogus minimum of roughly one full CFD even though Saxo accepts fractional amounts.

The corrected general contract is:

- `DefaultAmount` is never a minimum-size authority
- `InstrumentDetails.IncrementSize` is not treated as an amount increment
- `AmountDecimals` defines representable amount precision/quantum
- explicit `MinimumTradeSize` / `MinimumLotSize` are hard lower bounds when present
- account/product-specific Saxo information/precheck is used when metadata does not fully determine the minimum
- order precheck remains final authority
- no order is sent during sizing discovery/preflight
- Margin Envelope then determines the largest legal amount inside controlled pilot capital
- existing Product Admission can be safely revalidated without losing already user-supplied NBP/limited-loss acknowledgement

Regression coverage includes the observed fractional CFD pattern where `DefaultAmount=1`, `AmountDecimals=2` must allow fractional discovery, and a tiny pilot can select a fractional amount when Saxo margin data permits it.

This is intended as a reusable Saxo capability, not a special-case for UIC 4912.

### #249 — explicit sizing modes + LIVE ARMED indicator

Current AutoManager has two explicit entry-sizing policies:

- `MAX_WITHIN_PILOT` — default; choose the largest Saxo-precheck-approved amount inside the isolated pilot Margin Envelope
- `FIXED_AMOUNT` — use exactly the configured amount; fail/block rather than silently resize

Additional UI/runtime work:

- sizing preview without sending an order
- preview shows amount, margin, notional and free margin
- fixed lower-right red ARMED badge reflects persisted/runtime LIVE authority
- distinguish CLOSE-only, OPEN-only and full LIVE authority
- OPEN arming shows persisted pilot/global state explicitly
- flip strategy presentation renamed to `MACD Switch`; strategy behavior/key remains the same unless separately migrated later

## 5. Current Saxo sizing principles

Sizing must be instrument- and account-aware, not hardcoded by asset class.

General flow:

1. load exact Saxo Reference Data for account + UIC + AssetType
2. derive explicit hard minimum when Saxo exposes one
3. respect amount precision
4. use Saxo InfoPrice / order precheck to discover/verify legal candidate sizes when static metadata is incomplete
5. do not send an order during discovery
6. apply Product Admission
7. apply isolated pilot Margin Envelope / sizing policy
8. perform repeated/final Saxo precheck before POST
9. persist durable attempt before actual POST
10. never blindly retry an uncertain submission

Do not “fix” a small pilot by raising leverage to absurd values when sizing metadata is wrong. Fix the product sizing contract.

## 6. Entry authority and strategy behavior

Strategy and entry authority are separate dimensions.

Entry modes:

- `MANUAL_ENTRY_ONLY`: AutoManager may CLOSE, never OPEN/re-enter
- `AUTO`: valid OPEN/re-entry flows automatically through all safety gates
- `APPROVAL_REQUIRED`: CLOSE remains automatic; every OPEN/re-entry needs one-shot approval tied to the exact durable request

Changing entry authority disarms old OPEN authority. Old requests must not revive after a mode/arming change.

For long/flat:

- bearish cross while LONG → CLOSE
- wait for authoritative confirmed FLAT and settled close/P&L provenance
- later bullish cross while FLAT → OPEN LONG if entry authority and all gates are valid

No pyramiding. No direct one-order reverse. Flip always means `CLOSE → confirmed FLAT → OPEN opposite side`.

## 7. Shadow benchmark

PR #236 rebuilt the shadow benchmark as deterministic read-only replay over canonical history.

Key invariants:

- common observed starting exposure
- no bootstrap from instantaneous historical MACD regime
- first fully closed post-enrollment 30m bar establishes common price baseline
- independent strategy paths thereafter
- no shadow execution daemon
- no shadow authoritative P/L ledger
- no order authority

The desired current comparison is LIVE long/flat vs SHADOW long/short flip.

A future shared P/L chart is desirable, but only after an explicit comparable time-series contract exists for actual Saxo P/L vs paper P/L. Do not fabricate a visually attractive but semantically mismatched comparison series.

## 8. V1 retirement — important unfinished work

The user explicitly wants v1 fully retired so there are no hidden fallbacks, semantic reinterpretations or modules reading v2 data through v1 assumptions.

Open PR at handoff creation:

**#245 — `V2 cutover: quarantine retired v1 production paths`**

Branch: `fix/retire-v1-production-boundary`

The PR is open and GitHub currently reports it mergeable, but it was created before #246–#249. Do not merge it merely because GitHub says mergeable. Rebase/rebuild it on fresh `main`, rerun the full suite, and re-review its import graph against the current AutoManager/Saxo code.

#245 intent:

- remove Legacy developer navigation
- add a production-boundary regression test that walks active runtime/page imports
- fail CI if active production code reaches retired Information State / Decision State / Recommendation, legacy market-state/signal/overview/historical/forecast-contract stacks

Important: #245 is only the quarantine boundary. Full retirement still requires follow-on bounded capabilities.

Remaining v1 retirement categories to audit deliberately:

1. **Physical dead-code retirement**
   - delete genuinely unused v1 pages/modules after import-graph proof
   - do not delete files solely because their name ends in `_v1`

2. **Hardened AutoTrader modules with `_v1` names**
   - examples include hardened CLOSE/managed-position helpers currently imported by v2 execution
   - these may be current production code with old filenames, not legacy semantics
   - port/rename only with exact behavior-preserving tests; never bulk-delete based on filename

3. **Context persistence normalization**
   - Context v2 is authoritative semantically, but parts of persistence still use transitional `context_v2_snapshots` / `telegram_flow_*` storage while canonical `pg_v2_context_*` tables also exist
   - design a controlled migration/backfill/cutover, prove readers/writers, then retire transitional tables/paths
   - do not let a v2 object be interpreted using legacy `normalized_score` semantics

4. **Legacy adapters/contracts**
   - identify any adapter that accepts a v2 row/object but assumes v1 field meaning
   - add explicit contract tests at every cutover boundary

5. **Navigation and runtime entrypoints**
   - active pages/workers/services must not import retired semantic stacks even indirectly

The target is not “no files named v1”. The target is **one coherent v2 semantic/data path with no hidden v1 authority or reinterpretation**.

## 9. Database authority

Production web/stream/worker use PostgreSQL via `DATABASE_URL`. PostgreSQL is authoritative production persistence.

SQLite may remain useful for tests/local compatibility where explicitly intended, but do not introduce production fallback to SQLite.

When retiring v1 persistence, distinguish:

- current canonical v2 schema
- transitional tables that still support current readers/writers
- genuinely retired legacy schema

Migrate with backfill + dual-read/write only if necessary and for a bounded interval; establish an explicit cutover point and then remove the old path.

## 10. Existing safety invariants — preserve

- no LLM order placement or sizing
- no strategy-selected leverage
- no generic arbitrary Saxo OPEN path
- exact account + UIC + AssetType + direction Product Admission
- NBP/limited-loss acknowledgement is explicit user input; never infer it from product name or margin percentage
- one active LIVE controller per exact product
- CLOSE authority and OPEN authority are separate
- confirmed FLAT before OPEN
- settled authoritative close/P&L provenance before re-entry
- current settled pilot equity reread before sizing
- realized gains/losses adjust pilot equity; do not compound unrealized P/L
- final Saxo precheck immediately before POST
- durable execution attempt before POST
- uncertain submit is not blindly retried
- stale signals cannot reopen after risk-origin flattening
- changing entry authority must not revive older requests
- no pyramiding
- no one-order reverse; reverse via CLOSE → FLAT → OPEN

Do not weaken these to make the pilot easier to arm.

## 11. Recommended next sequence

### A. Verify current #249 surface from production

Before coding further, confirm in TradingDesk/AutoManager for exact Tech100 canonical product:

- selected market survives rerun
- LIVE strategy is long/flat
- SHADOW strategy is MACD Switch/flip
- entry mode is Full auto for the intended test
- sizing preview resolves fractional legal sizes from Saxo rather than 1.00 default amount
- chosen sizing mode is explicit
- CLOSE and OPEN/re-entry authority are shown distinctly
- ARMED badge accurately reflects persisted authority

Do not arm on the user's behalf. Activation is an explicit user action.

### B. Run the tiny technical LIVE pilot

Observe and record:

- source closed 30m MACD cross timestamp
- durable strategy evaluation / execution request
- CLOSE precheck/attempt/order acceptance
- authoritative FLAT reconciliation
- settled P/L reconciliation
- later bullish cross
- OPEN sizing/prechecks
- durable OPEN attempt/order acceptance
- exact re-entered position reconciliation
- shadow flip state over the same bars

The purpose is execution-chain proof, not strategy profitability.

### C. Resume v1 retirement

After the immediate pilot-readiness check, refresh #245 onto current main and continue the retirement program in bounded PRs. Prefer proof/guard first, then physical deletion/rename/migration.

### D. Later controlled batch: formal Position Guardian

Do not mix this into v1 retirement or the first MACD pilot. Later define its defensive authority, anomaly/regime inputs and AutoTrader re-evaluation interface explicitly.

## 12. Workflow

Use the established repository discipline:

- fresh `main`
- one bounded capability per branch/PR
- focused tests + full CI
- self-review diff and active import/runtime impact
- fresh-main check before merge
- expected-head guard on merge
- Railway deploy verification for runtime changes
- production smoke logs for execution/reconciliation changes

The repository has repeatedly shown why production verification matters: green CI alone did not catch prior Railway entrypoint/logging and Saxo response-shape issues.

## 13. What not to do next

- do not rewrite the whole AutoTrader stack while retiring v1
- do not special-case UIC 4912 sizing
- do not infer minimum amount from `DefaultAmount`
- do not infer legal exposure from `AmountDecimals` alone without Saxo validation when static metadata is incomplete
- do not merge #245 stale simply because GitHub says “mergeable”
- do not conflate bearish regime/trend with bearish short-term momentum; these can legitimately differ
- do not reintroduce legacy context `normalized_score` as v2 directional strength
- do not move AutoManager back into the sidebar
- do not turn Position Guardian into an exposure-creating engine
- do not add context/LLM authority to the first MACD test

## 14. Quick orientation files

Read these first:

- `docs/NEXT_ARCHITECT.md` — this file; operative handoff
- `docs/CURRENT_STATUS.md` — stable baseline and production status authority
- `tradingdesk_automanage_panel_v2.py` — current AutoManager surface
- `tradingdesk_autotrade_entry_gate_v2.py` — entry authority/Product Admission/Margin/sizing UI
- `autotrader_automanage_runtime_v2.py` — strategy runtime
- `autotrader_live_open_v2.py` — LIVE OPEN/re-entry path
- `autotrader_open_sizing_v2.py` — generalized Saxo sizing/precheck
- `autotrader_entry_policy_v2.py` — Product Admission / Margin policy
- `autotrader_shadow_benchmark_v2.py` — deterministic paper benchmark
- `autotrader_risk_control_v2.py` — current defensive risk engine / future Guardian seed

Open PR to inspect before continuing v1 retirement:

- #245 — V2 cutover: quarantine retired v1 production paths

Recent merges to inspect for context:

- #243, #244, #246, #247, #248, #249

---

Handoff principle: preserve the current working execution core, prove the tiny deterministic pilot, and retire v1 by explicit semantic/data cutovers rather than broad renames or deletions.
