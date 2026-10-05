# V2 execution vNext — 2026-10-05

## Decision

Replace the legacy V2 OPEN/CLOSE execution chain instead of continuing to patch it.
Keep V2 market data, strategy evaluation, desired-position production, engine/account ownership and operator control plane.

## Canonical runtime

`strategy desired inventory -> exact V2 account/instrument Saxo inventory -> deterministic delta -> Saxo instrument amount rules -> Saxo precheck -> durable reservation -> submit -> exact inventory reconciliation`

The exact assigned Saxo account + UIC + asset type is the only inventory boundary. Portfolio-wide positions and V3 inventory must never influence V2 execution.

## Invariants

- Saxo exact inventory is source of truth.
- One V2-owned account/instrument boundary per runtime instance.
- Desired and actual inventory use signed amounts: LONG positive, SHORT negative, FLAT zero.
- OPEN, ADD, REDUCE and CLOSE are derived from the same delta planner.
- Reversal is close-first. Opposite OPEN is considered only after a later cycle proves FLAT.
- Amount is normalized to Saxo's instrument amount step; it is not hard-coded to 0.01 or 0.1.
- Saxo precheck is a broker validity check, not a strategy layer.
- Durable reservation happens before external POST.
- Ambiguous POST result becomes UNKNOWN and is reconciled from Saxo inventory; never blind-retried.
- A pending request is keyed to exact account + UIC + asset type and expected post-order inventory.
- V3 runtime and state are untouched.

## Migration

1. Build and test pure deterministic planner. [done]
2. Build V2-owned exact inventory adapter and readiness/precheck surface.
3. Build durable order guard + reconciliation for vNext.
4. Connect existing V2 desired-position output in shadow mode; compare legacy and vNext plans.
5. Run a small live smoke test on the V2 account.
6. Route V2 LIVE authority to vNext.
7. Disable legacy OPEN/CLOSE consumers only after vNext live reconciliation is proven.

## Operator state

The replacement runtime should expose `READY`, `ARMED`, `LIVE`, `PENDING`, `BLOCKED`, and `RECONCILED`. `BLOCKED` must carry the concrete failing prerequisite rather than a combined legacy error.
