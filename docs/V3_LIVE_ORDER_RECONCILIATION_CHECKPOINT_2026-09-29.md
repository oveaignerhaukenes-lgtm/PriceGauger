# V3 Saxo LIVE order safety — implementation checkpoint (2026-09-29)

## Implemented on this draft branch
- Persist a unique unresolved order reservation for each Saxo account/UIC/asset type before the external Saxo POST.
- Store the requested quantity, side, expected signed post-trade inventory, broker order ID, and current resolution state.
- Keep timeout, missing order ID, unknown outcome and incomplete audit fail-closed; never retry a potentially submitted order.
- Read Saxo audit for an exact confirmed FinalFill, require a full matching filled quantity and side, then independently refresh exact Saxo inventory before marking RECONCILED.
- Run pending-order reconciliation before new market-data/strategy evaluation; continue the following cycle rather than sending a new order in the reconciliation cycle.
- Unit and source-integration tests cover restart persistence, duplicate reservation, account isolation, wrong account/product, partial fills, duplicate audit matches, stale/wrong inventory and ordering.

## Explicit remaining gates
1. Validate Saxo LIVE response and audit field shapes against read-only real broker data; especially ClientKey, OrderId, BuySell, fill aggregation and pagination. No real order should be submitted as part of read-only verification.
2. Verify the worker runs with shared PostgreSQL, including concurrent worker reservations and process restarts, not just SQLite unit tests.
3. End-to-end simulation of accepted, rejected, timeout, partial-fill and reversal paths; ensure existing V2 controller cannot operate the same account/instrument simultaneously.
4. Add operator-facing unresolved-order inspection and explicit reviewed recovery for an UNKNOWN order without a broker ID or older than audit lookback.
5. Independently validate the V3 trailing strategy risk limits and CLOSE -> CONFIRM_FLAT -> OPEN reversal path. Do not set its live_route_enabled until these gates are met.

This PR is intentionally draft. Green CI alone is not Saxo execution validation.
