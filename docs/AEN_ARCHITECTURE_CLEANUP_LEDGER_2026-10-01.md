# PriceGauger — Architecture Cleanup Ledger

**Started:** 2026-10-01  
**Status:** ACTIVE / living document  
**Purpose:** Shared architectural audit, cleanup backlog, decision log, and verification ledger for PriceGauger.

This document is intentionally not a one-off report. Future architects should update it as findings are verified, work is completed, or new debt is discovered.

## Non-negotiable operating constraints

1. **V2 and V3 remain independently runnable.** They will coexist for comparative live/SIM testing for the foreseeable future.
2. **V2 and V3 must be hard-separated.** Separate authority, account ownership, runtime state, strategy state, execution state and UI control boundaries. No accidental cross-engine imports or shared mutable authority.
3. **Do not destabilize working execution while cleaning architecture.** Refactor incrementally behind tests and explicit runtime verification.
4. **Transparency is a first-class requirement.** It should be possible to answer: what strategy decided, which engine owned the decision, which account/product it targeted, what order was requested, what Saxo returned, and what state was reconciled.
5. **One authoritative path per responsibility.** Transitional duplicates must have an explicit retirement path.
6. **Fail visibly, not mysteriously.** Runtime ambiguity, stale state, rejected requests and reconciliation failures need inspectable diagnostics.

## Current architectural diagnosis

PriceGauger has accumulated several generations of UI, execution, strategy and diagnostic code during rapid iteration. Individual components often work, but the global dependency graph is becoming difficult to reason about. The main risk is no longer only a local bug: it is uncertainty about which layer currently owns a behavior.

The immediate objective is therefore **controlled simplification**, not a rewrite.

---

# A. V2 / V3 hard separation — P0

## Finding A1 — V2 Simple UI imports V3 authority/state

Observed in `tradingdesk_automanager_simple_v1.py`:
- `autotrader_v3_macd_trailing_v1.STRATEGY_KEY_V3`
- `autotrader_v3_live_authority_v1`
- `autotrader_v3_sim_authority_v1`

This creates an architectural cross-link between engines that should be independently operable.

### Target

Introduce an explicit engine boundary. A V2 UI/controller must only manipulate V2 authority. A V3 UI/controller must only manipulate V3 authority. Shared UI may query an engine-neutral read model, but may not mutate both engines implicitly.

### Verification

- [ ] V2 control modules contain no V3 authority imports.
- [ ] V3 control modules contain no V2 authority mutation imports.
- [ ] V2 can be enabled/disabled without changing V3 runtime state.
- [ ] V3 can be enabled/disabled without changing V2 runtime state.
- [ ] Different Saxo accounts can run V2 and V3 concurrently.
- [ ] Same-account collision is rejected explicitly and diagnostically.

---

# B. Canonical V2 control plane — P0

## Finding B1 — overlapping generations of V2 controls

Known surfaces include:
- `tradingdesk_automanager_simple_v1.py` — current `ENGINE V2 · LIVE` control surface.
- `tradingdesk_strategy_family_ui_v1.py` — family/timeframe builder and strategy activation.
- `tradingdesk_autotrade_entry_gate_v2.py` — older detailed execution-gate / Margin Envelope controls.

### Problem

Multiple surfaces can make it unclear whether selecting a strategy, pressing `Bruk`, arming LIVE, choosing a timeframe or changing sizing is merely configuration or actually changes execution authority.

### Target

One canonical V2 state transition model:

`account -> product -> strategy instance -> configuration -> execution authority -> target -> durable request -> Saxo -> reconciliation`

UI may have several views, but all views must call the same canonical transitions.

### Verification

- [ ] Exactly one authoritative V2 LIVE enable/disable transition.
- [ ] Exactly one authoritative strategy-switch transition.
- [ ] Strategy selection does not silently duplicate an authority transition elsewhere.
- [ ] Sizing policy has one source of truth.
- [ ] Old gate UI is either read-only diagnostics or retired.

---

# C. Transitional / legacy layer retirement — P1

## Finding C1 — current facade still depends on private legacy internals

`tradingdesk_automanage_panel_v2.py` explicitly identifies itself as a transitional facade and imports from `tradingdesk_automanage_panel_legacy_v2.py`, including private helpers such as:
- `_pnl_enrollments_for_context_v2`
- `_render_automanager_activity_log_v2`

### Target

Extract still-valid capabilities into explicit modules:
- V2 read model
- activity/event log renderer
- P/L comparison/read model

Then make `legacy_v2` deletable rather than foundational.

### Verification

- [ ] No production facade imports private `_...` functions from legacy module.
- [ ] Legacy module has zero runtime callers before deletion.
- [ ] Historical P/L behavior remains unchanged.

---

# D. Trading runtime vs analysis/replay separation — P1

## Finding D1 — live TradingDesk facade owns too many workloads

The current facade can invoke live controls plus P/L, Three Trader Lab, Supervisor Lab, Scoreboard, Hybrid Lab and Storage Audit. Comments in the code already document that historical replay workloads can hold the Streamlit session long enough for the live chart WebSocket to disconnect.

### Target

Separate:
- **Live plane:** chart, account/product position, engine status, target, execution/reconciliation, minimal diagnostics.
- **Analysis plane:** historical replay, benchmark, Strategy Lab, scoreboards, storage audits.

The analysis plane may consume persisted runtime data but should not interfere with live refresh cadence.

### Verification

- [ ] Live chart refresh is independent of replay computation.
- [ ] Opening analysis panels cannot stall live execution UI.
- [ ] Heavy historical queries are lazy/on-demand.
- [ ] Live runtime does not depend on analysis rendering.

---

# E. Observability and debuggability — P0/P1

This is now a core product requirement, not optional developer tooling.

## Required canonical execution trace

Every automated decision should be traceable with stable identifiers through:

`engine -> trader/pilot -> strategy -> signal -> desired target -> sizing -> precheck -> durable request -> broker order -> broker response -> observed position -> reconciliation`

### Proposed work

- [ ] Define stable `engine_id` (`v2`, `v3`) on all runtime/execution records where ambiguous today.
- [ ] Define/carry `decision_id` or equivalent correlation ID from strategy decision through reconciliation.
- [ ] Ensure `request_key` / broker order identifiers are visible in diagnostics.
- [ ] Persist reason codes for `NOOP`, `BLOCKED`, `OPEN`, `CLOSE`, `REDUCE`, `REVERSE`.
- [ ] Show desired target vs observed broker position side by side.
- [ ] Show last successful reconciliation timestamp.
- [ ] Show unresolved durable requests prominently.
- [ ] Show which exact account/product/engine currently owns authority.
- [ ] Add a compact runtime timeline rather than relying on scattered Streamlit messages.

## Desired diagnostic question

For any surprising trade, an architect should be able to answer in minutes:

> Why did this engine believe this action was correct, what exact request did it send, what did Saxo accept/reject, and why does current persisted state differ or agree?

---

# F. State ownership audit — P1

Audit all mutable state categories and assign exactly one owner:

| State | Intended owner | Status |
|---|---|---|
| V2 execution authority | V2 engine | audit |
| V3 execution authority | V3 engine | audit |
| account assignment | engine/fleet boundary | audit |
| strategy configuration | respective engine | audit |
| sizing/capital allocation | respective engine policy | audit |
| desired target | respective engine runtime | audit |
| durable request | execution lifecycle | audit |
| observed Saxo position | broker reconciliation/read model | audit |
| chart markers | presentation derived from persisted events | audit |
| SIM state | respective SIM runtime | audit |

Special attention: Streamlit `session_state` must not become authoritative execution state. It should hold presentation state only unless explicitly documented otherwise.

---

# G. Naming/version debt — P2

Current names mix product generation and implementation revision: `v1`, `v2`, `v3`, `simple_v1`, `legacy_v2`, chart `...v5` aliased as `...v1`, etc.

Do **not** mass-rename during live stabilization. First create a map:

`public responsibility -> canonical module -> compatibility facade -> deprecated module`

Then rename/delete only when imports and tests make the cutover safe.

- [ ] Produce canonical module map.
- [ ] Mark compatibility facades explicitly.
- [ ] Stop adding new functionality to legacy modules.
- [ ] Delete dead generations after caller audit.

---

# H. Error taxonomy — P1

Current troubleshooting will improve substantially if errors are classified rather than surfaced as arbitrary strings.

Suggested categories:
- `CONFIGURATION`
- `AUTHORITY`
- `MARKET_CLOSED`
- `SIGNAL/STRATEGY`
- `SIZING`
- `PRECHECK`
- `REQUEST_PERSISTENCE`
- `BROKER_REJECT`
- `BROKER_TRANSPORT`
- `RECONCILIATION`
- `STALE_DATA`
- `AMBIGUOUS_STATE`
- `UI_ONLY`

- [ ] Inventory current exception/reason strings.
- [ ] Normalize runtime reason codes without hiding original broker details.
- [ ] Surface category + engine + account + product + correlation ID.

---

# I. Database/schema audit — P1

The database has become part of the control plane. Audit tables for:
- engine ownership
- account/product keys
- uniqueness assumptions
- pending/unresolved request semantics
- timestamps/timezones
- stale rows from retired generations
- migrations/schema creation occurring at runtime
- indexes on hot reconciliation/read paths

- [ ] Produce table-to-owner map.
- [ ] Identify tables shared accidentally by V2/V3.
- [ ] Verify uniqueness constraints match actual engine/account/product boundaries.
- [ ] Verify restart/redeploy recovery from persisted state.

---

# J. Tests and CI as architecture guardrails — P0/P1

Existing tests already protect shared UI, live-close wiring and V2 cutover behavior. Extend this into explicit architectural tests.

Required additions:
- [ ] import-boundary test: V2 control plane cannot import V3 authority modules and vice versa.
- [ ] concurrent-engine test: V2 account A + V3 account B.
- [ ] collision test: same account/product cannot accidentally acquire dual authority.
- [ ] restart/recovery test for unresolved durable requests.
- [ ] target -> request -> reconcile state-machine tests.
- [ ] market-closed behavior test that distinguishes pause from execution failure.
- [ ] chart marker provenance test: manual vs V2 vs V3.

---

# K. UI transparency — P1/P2

The UI should expose the architecture rather than obscure it.

For each active engine panel, show compactly:
- engine: V2 / V3
- account
- product
- strategy + timeframe
- LIVE/SIM/OFF
- desired target
- observed position
- last decision + reason
- last broker action
- reconciliation status

Manual trades should remain visually distinct from V2 and V3 chart events. Avoid verbose marker text; provenance should be encoded consistently and details available on inspection.

---

# L. Work sequencing

## Phase 0 — while market is paused / before next live verification

Safe inspection/documentation only:
- [x] Start architecture cleanup ledger.
- [x] Record V2/V3 hard-separation requirement.
- [x] Record canonical V2 control-plane issue.
- [x] Record transitional legacy dependency.
- [x] Record live-vs-analysis workload coupling.
- [ ] Continue dependency/import audit.
- [ ] Continue DB/state ownership audit.
- [ ] Map execution lifecycle for V2 and V3 side by side.

## Phase 1 — next live window

Do not refactor first. Verify current behavior:
- [ ] V2 Tech100 OPEN.
- [ ] V2 HOLD/no unnecessary cancel/close.
- [ ] V2 CLOSE/REVERSE.
- [ ] V3 remains unaffected.
- [ ] Capture exact event/request/reconciliation trail.

## Phase 2 — safe boundary cleanup

- [ ] Remove V3 authority mutation from V2 UI.
- [ ] Introduce/strengthen engine-account ownership boundary.
- [ ] Add architectural tests.
- [ ] Extract legacy read-model helpers.

## Phase 3 — observability

- [ ] Canonical correlation IDs / execution timeline.
- [ ] Error taxonomy.
- [ ] Runtime ownership/status panel.
- [ ] unresolved-request/reconciliation diagnostics.

## Phase 4 — structural cleanup

- [ ] Retire dead legacy UI/control generations.
- [ ] Separate heavy analysis workloads from live plane.
- [ ] Simplify naming/module map.
- [ ] Delete proven-dead code only after caller/test audit.

---

# M. Rules for future architects

When touching this area:

1. Read this ledger first.
2. Update findings rather than creating disconnected cleanup reports.
3. Never solve a V2 bug by quietly mutating V3 state, or vice versa.
4. Preserve concurrent V2/V3 operation on different accounts.
5. Prefer removing ambiguity over adding another safety/control layer.
6. Prefer a visible state transition over hidden UI side effects.
7. Do not add a second implementation when the correct fix is to repair the canonical one.
8. After each change, document: **what owns the behavior now, what old path became obsolete, and how it was verified.**

---

# N. Audit log

## 2026-10-01 — initial holistic review

Confirmed/observed:
- V2 Simple Core still has direct V3 authority imports.
- V2 has overlapping control generations.
- Current AutoManage facade remains transitional and depends on private legacy helpers.
- Live TradingDesk and heavy analysis/replay remain coupled enough that code comments document WebSocket starvation risk.
- Existing tests provide a useful base for incremental rather than rewrite-style cleanup.

User/product direction recorded:
- V2 and V3 should both remain available for comparison testing for now.
- They must nevertheless be fully separated architecturally.
- The system has become difficult enough to troubleshoot that transparency, state ownership and diagnostic traceability are now explicit cleanup goals.

**Next audit focus:** dependency graph, database/state ownership, execution lifecycle, duplicated runtime paths, error handling and diagnostics.
