# PriceGauger — New Project Bootstrap

**Date:** 2026-10-06  
**Purpose:** minimal authoritative handoff for a fresh ChatGPT Project / next architect.  
**Start from:** fresh `main`. At handoff creation, `main` is `765fd622a6da4867e79f42afeac0a931fac1cde7`.

Read this file first. Do **not** preload the full historical handoff archive or the old long-form `CURRENT_STATUS.md` unless a concrete question requires it. Git history and older docs remain available as evidence.

## 1. Current milestone

AutoTrader V3 has crossed the important production milestone:

```text
canonical V3 instance registry
→ per-instance config
→ LIVE authority
→ ENGINE_V3 account ownership
→ per-instance runtime strategy resolution
→ exact account/UIC/asset execution
→ durable pending-order state
→ Saxo execution
→ reconciliation
```

This chain is now observed end-to-end in production.

### Production evidence

Canonical production V3 instance:

- instance / pilot: `b6008676-ec57-50e9-9cbf-3b0577c643ab`
- Saxo account: `1068427INET` (Autotrader)
- instrument: US Tech 100 NAS
- UIC: `4912`
- asset type: `CfdOnIndex`
- LIVE authority: armed
- canonical ownership: `ENGINE_V3 / b6008676-ec57-50e9-9cbf-3b0577c643ab`
- UI/catalog strategy key: `macd`
- canonical runtime key: `macd-trailing-v1`

Production worker after the 2026-10-06 cutover repeatedly logged:

```text
v3 LIVE discovered enabled instances=...
v3 LIVE candidate instance=b600... armed=True
v3 LIVE active owned armed instances=1
v3 runtime ... status=RUNNING
```

Observed end-to-end execution/reconciliation on the same exact account/product:

```text
actual=0.03 → target=0.02 → REDUCE Sell 0.01
→ later RECONCILED actual=0.02 expected=0.02

actual=0.02 → target=0.01 → REDUCE Sell 0.01
→ later RECONCILED actual=0.01 expected=0.01

actual=0.01 → target=0.02 → ADD Buy 0.01
→ later RECONCILED actual=0.02 expected=0.02

actual=0.02 → target=0.03 → ADD Buy 0.01
→ later RECONCILED actual=0.03 expected=0.03
```

Do not infer future inventory from this handoff; always read fresh runtime/broker evidence before making claims about current position state.

A second enabled V3 registry instance was later observed:

- `f75cdc83-168b-5eb4-9224-ce73a058b6d3`
- currently observed as `armed=False`

Its presence is not LIVE authority. Multi-instance discovery is expected; only armed + correctly owned instances may execute.

## 2. Account boundary

Keep the engine/account split explicit:

```text
V2 / Lager account:      1084854INET
V3 / Autotrader account: 1068427INET
```

Historical V2 enrollment metadata existed on the V3 account. The 2026-10-06 migration work repaired the canonical V3 identity and ownership path without treating stale V2 metadata as current execution authority.

Never broaden this into “any enrollment means ownership”. Persistent engine-account ownership and explicit authority gates are the canonical boundaries.

## 3. V3 architecture boundary

Human/UI model:

```text
TradingDesk
= cockpit for one selected V3 instance

AutoTrader V3
= fleet/configuration view for multiple V3 instances
```

Runtime model:

```text
V3 engine instance
→ instance config
→ catalog strategy key
→ StrategySpecV3.runtime_key
→ execution strategy registry
→ closed-bar target
→ exact inventory delta
→ durable order/reconciliation path
```

Important distinction:

- product/UI catalog key `macd`
- runtime execution key `macd-trailing-v1`

The adapter in `autotrader_v3_runtime_instances_v1.py` must resolve catalog keys through `StrategySpecV3.runtime_key`. Do not mutate persisted config merely to satisfy the runtime registry.

## 4. 2026-10-06 cutover work that is now canonical

The completed tranche established:

- V3 LIVE discovery from the canonical V3 instance registry rather than V2 enrollments.
- Exact V3 account ownership gate before execution.
- Fail-closed behavior on ownership mismatch.
- Production identity repair for the pre-existing V3 LIVE pilot.
- One-time legacy ownership backfill for the pre-ownership V3 pilot.
- Distinction between stale V2 enrollment metadata and actual V2 LIVE authority.
- Catalog-key → runtime-key resolution.
- Regression coverage for multi-instance discovery, unarmed skip, account isolation, ownership mismatch, pending-order isolation, legacy identity preservation, and runtime strategy resolution.

All execution-sensitive changes were taken through CI, fresh-main checking, guarded merge, exact Railway deployment verification and production runtime inspection.

## 5. Invariants — do not weaken

- One Saxo account may not be simultaneously owned by V2 and V3.
- Registry membership alone is not execution authority.
- LIVE authority alone is not enough; exact account ownership must also match.
- Unarmed instances must remain inert.
- Pending-order state is scoped by exact account + UIC + asset type.
- No blind retry after uncertain broker submission.
- Reconciliation is authoritative after submission.
- A green CI/deploy is not proof of broker execution; inspect runtime/reconciliation evidence.
- UI/catalog strategy identity and execution runtime identity are separate contracts.
- Do not “fix” migration issues by silently arming instances, transferring account ownership, or clearing pending-order state.
- Preserve V2/Lager and V3/Autotrader independence while V2 still exists.

## 6. Known follow-up / technical debt

These are **not** blockers for the completed LIVE milestone:

1. **V3 SIM runtime** still has legacy dependence on V2 enrollment discovery. Decide deliberately whether SIM should be cut over to the same instance model; do not assume LIVE and SIM must change together.
2. **Historical docs** are large and often describe superseded migration stages. Use them only when tracing provenance.
3. **Old V2 state** still exists by design for the separate Lager engine. Do not perform broad V2 cleanup merely because the V3 cutover succeeded.
4. Continue observing the new multi-instance path before scaling execution scope or capital.
5. The second V3 instance `f75cdc83-168b-5eb4-9224-ce73a058b6d3` was observed enabled but unarmed. Resolve its intended role from fresh config/UI state before changing it.

## 7. Natural next discussion

The next step should be a **strategy/product discussion**, not another automatic architecture refactor.

Useful decisions include:

- which V3 base strategies should be production-ready next;
- whether SIM should adopt the canonical instance model now;
- how modifiers should compose around base strategies;
- how aggressive multi-instance testing should be;
- when to retire remaining transitional V2 compatibility layers;
- what evidence threshold is required before increasing capital/exposure.

Do not implement these merely because they are listed here. They are product decisions for the user.

## 8. Minimal reading order for a fresh project

Start with:

1. this file;
2. fresh `main`;
3. only the modules/tests directly relevant to the requested change.

Read these deeper docs only when needed:

- `docs/AEN_ARCHITECTURE_CLEANUP_LEDGER_2026-10-01.md`
- `docs/AEN_ARCHITECT_19_HANDOFF_2026-10-06.md`
- `docs/AEN_CANONICAL_MODULE_MAP_2026-10-02.md` if module ownership is unclear
- older handoffs only for historical provenance

Do **not** use the old long-form `docs/CURRENT_STATUS.md` as the first context load.

## 9. Working method

For each bounded change:

```text
fresh main
→ inspect canonical code + focused tests
→ one bounded branch/change
→ focused tests
→ full CI
→ fresh-main check
→ expected-head guarded merge
→ verify exact Railway SHA
→ inspect runtime evidence
→ checkpoint/handoff
```

Keep the conversation alive during CI/deploy, but prefer short progress updates rather than one very long assistant turn.

Ask the user only when a real product/strategy decision is required. Routine implementation, testing, merge and deployment follow-through should be completed autonomously.

## 10. New ChatGPT Project recommendation

For the new ChatGPT Project:

- connect the same GitHub repository;
- use this file as the bootstrap handoff;
- do not import the old project conversation history wholesale;
- let repository docs, tests and git history carry technical continuity;
- start new architect chats at natural milestones rather than allowing one chat to accumulate the entire project history.

A suitable first prompt is:

> Hei Aen. Dette er den nye PriceGauger-prosjektmappen. Les `docs/PRICEGAUGER_NEW_PROJECT_BOOTSTRAP_2026-10-06.md`, sjekk fresh main og produksjonsstatus, og gi meg en kort vurdering av hvor vi står før vi diskuterer strategi videre.
