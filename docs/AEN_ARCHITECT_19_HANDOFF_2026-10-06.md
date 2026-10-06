# AEN Architect 19 handoff — 2026-10-06

## Milestone reached
The V3 product UI has been split at the correct architectural boundary:

- **TradingDesk is the workspace for one V3 instance.** It exposes the shared canonical instance controls for strategy, timeframe, modifiers/options, budget and exposure next to the strategy/SIM workspace.
- **AutoTrader V3 is the fleet view.** It shows all V3 instances, LIVE/SIM state, strategy, runtime state, current broker P/L, 24h execution count, relative open-P/L visualization, execution diagnostics and an expandable management surface.
- Both surfaces render the same `autotrader_v3_instance_controls_ui_v1.py`; there is no page-local strategy/config state.
- V3 instance registry is durable and preserves the existing production instance identity during bootstrap.
- Account assignment is now account-level unique for enabled V3 instances. The Saxo account picker shows all returned accounts; occupied accounts remain visible with a lock and the owning V2/V3 owner, while creation is disabled for them.
- PR #636 merged as `3b2d37f132e5e1ad0007d93ee4dda18f20bc1952`; CI passed and `pricegauger-web` Railway deployment `5ba8268d-f967-4f35-883e-b123d1d9fff8` reached SUCCESS.

## Earlier work in this architect session
V3 chart provenance was moved to a canonical durable execution-event ledger instead of reconstructing trades from V2 enrollment/order state. Exact reconciliations create canonical execution events; chart marker projection reads the ledger. This was merged before the fleet UI work.

## Important remaining P0 — LIVE multi-instance runtime cutover
The **management/configuration side of multi-instance is complete**, but the LIVE worker still sources its active traders from legacy V2 strategy enrollments in `autotrader_v3_live_runtime_v1.py`. Therefore do **not** call live multi-instance execution complete yet.

The intended cutover is straightforward and already has the supporting module `autotrader_v3_runtime_instances_v1.py`:

1. Replace V2 enrollment discovery in `run_v3_live_cycle_v1()` with `load_v3_runtime_instances_v1()`.
2. Filter each instance by its own V3 LIVE authority.
3. Before any execution path, require account ownership `ENGINE_V3` with `owner_key == instance_id`; fail closed on mismatch.
4. Resolve strategy from the per-instance canonical config (the runtime-instance adapter already does this).
5. Keep pending order, inventory, execution policy, sizing, reconciliation and canonical execution ledger keyed/bounded by that exact instance/account/UIC/asset tuple.
6. Tests must prove: two armed instances on different accounts are independently visited; unarmed instance is skipped; ownership mismatch is blocked; one instance's pending state cannot block another account; existing production instance identity survives bootstrap.
7. CI -> merge -> Railway worker deploy -> verify existing production instance unchanged before adding/arming a second account.

Architect 19 attempted this runtime source cutover, but the ChatGPT GitHub connector safety layer blocked the mutation because the file contains live financial execution code. Do not work around that control. The UI/registry work was kept separate and safely merged.

## Product direction
Continue treating configuration as **instance-owned**, never page-owned:

`V3 instance -> Saxo account/product -> strategy -> modifiers -> budget/exposure -> authority -> execution -> reconciliation -> canonical execution event`

TradingDesk and AutoTrader are merely two projections/control surfaces over that same instance.

Once the LIVE runtime cutover is independently completed and verified, this is the natural point to consider V3 multi-instance a true milestone and then decide whether V2 execution can be retired.
