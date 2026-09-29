# AEN handoff — V3 manual-seeded LIVE Tech100, 2026-09-30 01:33 CEST

## Executive status
V3 Trailing manual-seeded, reduce-only pilot is merged and deployed. **One actual V3 reduction order was submitted**, but **subsequent order reconciliation is BLOCKED**. Do not claim that the end-to-end pilot is finished or that V3 can safely continue trading. The user should manage the remaining Saxo position manually until reconciliation is diagnosed. Avoid placing any further LIVE orders as part of debugging without renewed explicit user authorization.

GitHub: PR #569 (manual-seeded reduce-only V3 Trailing) squash e123e8f92eea56b7f148511070b55db38b3e73e3. PR #570 (Saxo fractional quantity normalization) squash e0940eb8bcc3e3980d69d605879214b713ad7620. Main CI run 36643238403 passed. All four Railway services SUCCESS on e0940eb8bcc3e3980d69d605879214b713ad7620 at handoff.

## Real pilot observations (source: user Saxo screenshot and Railway worker deploy logs)
- User opened **SHORT -0.03** US Tech 100 NAS, Saxo UIC 4912, on dedicated Autotrader account **1068427INET** (not V2 Lager account).
- The V3 panel showed Motor ON / SHORT and later **LIVE BLOCKED: Order reconciliation unavailable: RuntimeError** at approximately 01:30 CEST. Screenshot is in preceding project conversation; do not infer order-fill state from the UI alone.
- Before PR #570, repeated Saxo prechecks failed with Norwegian message: "Antall desimaler for brøkbeløp overskrider den konfigurerte verdien." They were rejected before order POST.
- PR #570 floors trailing REDUCE/CLOSE quantity to two decimals (0.01 steps) using Decimal ROUND_DOWN before precheck; sub-0.01 reduction is blocked. This was not a comprehensive broker metadata-driven order-step solution; confirm Saxo's actual instrument precision.
- On new deployment **f7c32791-44fa-4633-905f-022699521230**, Railway worker logs show **2026-09-29 23:17:27 UTC (01:17:27 CEST):** `v3 LIVE executed trader=b6008676-ec57-50e9-9cbf-3b0577c643ab step=REDUCE side=Buy amount=0.01`; worker also logged `v3 LIVE executed mutations=1`. This means Saxo returned an OrderId and the runtime marked the request SUBMITTED. It does **not** prove the order filled or that inventory is now -0.02.
- Subsequent screenshot shows BLOCKED on reconciliation; investigate exact traceback/DB state rather than bypassing the guard.

## Code architecture
- `worker.py` runs `run_v3_live_cycle_v1` in normal worker cycle.
- `autotrader_v3_live_runtime_v1.py` filters LIVE enrollments and explicit `live_authority_armed_v3`, reads broker positions, computes closed 5m MACD, plans target vs actual inventory. Trailing route only allows REDUCE/CLOSE and never OPEN/ADD. Saxo precheck, durable reserve, SUBMITTING, POST, SUBMITTED, then next-cycle reconciliation.
- `autotrader_v3_order_guard_v1.py` maintains durable unique active account/uic/asset lock. Existing pending orders are reconciled before new strategy evaluation.
- `autotrader_v3_order_reconciliation_v1.py`: `reconcile_pending_v3` requires account_key AND client_key AND broker_order_id, calls `fetch_exact_order_audit_v3`, then fresh `_position_observations_v2`, then `verified_reconciled_inventory_v3`. Exact confirmed terminal FinalFill quantity plus fresh matching inventory must agree with expected inventory.
- `autotrader_v3_order_audit_v1.py`: Saxo `cs/v1/audit/orderactivities` fetch and exact order-fill validation.
- `autotrader_v3_live_saxo_v1.py`: `accounts()` reads `port/v1/accounts/me`, `net_positions_exact()` reads netpositions. Runtime currently uses V2 `_position_observations_v2` for reconciliation.
- `autotrader_v3_closed_bar_driver_v1.py`: persisted closed-bar strategy target, 5m MACD.
- `tradingdesk_automanager_simple_v1.py`: `ENGINE V3 · LIVE` toggle and runtime status UI.

## Immediate next task: diagnose reconciliation failure without submitting another order
1. Inspect latest Railway worker logs around **2026-09-29 23:17–23:33 UTC** and obtain actual exception from the `reconcile_pending_v3` path. Runtime currently catches exception and only persists `Order reconciliation unavailable: {type(exc).__name__}`, obscuring details. Add sanitized, bounded diagnostic logging (exception type + safe message, no credentials/tokens); include pending request_key/order ID in logs if safe.
2. Inspect `fetch_exact_order_audit_v3` request/response shape against Saxo documentation and observed data, especially `ClientKey` availability in `port/v1/accounts/me`, account matching, pagination, audit order ID, fill event nomenclature, cumulative vs incremental filled amount, and terminal FinalFill semantics.
3. Check whether `_position_observations_v2` fails with RuntimeError or produces ambiguous account-scoped positions. Review actual Saxo broker position and audit **read-only**. Do not fabricate order fills. Check durable pending order state from DB using available approved tooling; Railway connector may not provide SQL.
4. Fix the verified cause with targeted tests covering the observed response shape, error visibility, and reconciliation. Keep existing order lock until independent Saxo evidence verifies the prior order's exact terminal fill and fresh inventory. If broker evidence is insufficient, require manual confirmation; never silently mark RECONCILED or automatically retry.
5. GitHub PR, CI, merge, verify all four Railway deployments and worker logs. Then confirm user position/current account state before any resumed LIVE test.

## Other important considerations
- The V3 trailing pilot is reduce-only. User's small 0.03 short was intended to test 0.01 reductions. Do not accidentally enable new OPEN/ADD or confuse with V3 histogram route, which has a separate LIVE path.
- A previous handoff noted risk of strategy target beginning at zero independent of manually seeded broker inventory; initial reductions may be immediate. No fixed NOK loss cap is guaranteed by this pilot.
- Reconciliation can be BLOCKED by missing ClientKey, audit exceptions, mismatch of expected vs actual inventory, absent FinalFill, or stale/ambiguous position reads. Distinguish exception from normal `False` verification: screenshot specifically says **RuntimeError**, suggesting an exception in read/audit path rather than merely no confirmed fill.
- User prefers autonomous end-to-end engineering and active CI/deploy follow-through, without repeated requests for decisions. Ask only when a real external choice or renewed LIVE trading authorization is needed.

## Verification at handoff
GitHub main CI run 36643238403 completed success. Railway latest four service deployments on e0940eb8bcc3e3980d69d605879214b713ad7620: worker f7c32791-44fa-4633-905f-022699521230 SUCCESS; stream 60c1d171-7a08-44a6-b48c-1c253c461269 SUCCESS; web ad7106dd-53a6-423c-abe2-0fd5c6845966 SUCCESS; Spring engine db374d73-e234-4d90-9b7e-19c8dfbe9997 SUCCESS.
