# Handoff: V3 manual-seeded LIVE Tech100 — 2026-09-30 01:33 CEST

## Executive status (read first)

**A REAL V3 LIVE ORDER WAS SUBMITTED** after the order-precision fix. Railway worker production log at **2026-09-29 23:17:27 UTC**: `v3 LIVE executed trader=b6008676-ec57-50e9-9cbf-3b0577c643ab step=REDUCE side=Buy amount=0.01`; next line: `v3 LIVE executed mutations=1`. This is a reduce-only **BUY** against the user's manually opened **SHORT -0.03** US Tech 100 NAS CFD, Saxo UIC 4912, Autotrader account **1068427INET**. This confirms a successful Saxo order submission with an OrderId returned, **not** independent proof of execution/fill. The user's subsequent V3 UI screenshot (~01:30 CEST) says **`LIVE BLOCKED: Order reconciliation unavailable: RuntimeError`**, so the durable pending-order lock is still blocking further V3 orders. **Do not clear this lock without read-only broker evidence of exact fill and exact account/UIC inventory.** User should manage open risk manually in Saxo until reconciled.

## User intent / pilot contract

User opens 0.03 manually in Saxo, then arms V3 to manage it. Actual position screenshot showed **-0.03 SHORT**, not LONG. For this low-capital pilot, trailing strategy is **reduce/close only**; no opening, adding, or flipping into opposite exposure. Target risk budget ~10–15 NOK is a user goal, **not guaranteed**. User prefers minimum operational friction and wants agent to autonomously fix code, run CI, merge, watch Railway, and hand off when necessary. Do not ask user to make engineering decisions that can be resolved from repo/logs. Do not submit manual broker orders on their behalf.

## Work completed

1. Prior durable Saxo guard and reconciliation: PR #567, merged `0f665486f0cfed33f1e9219cae85bd4d51260dae`. Includes durable pending order guard, exact fill and inventory reconciliation, distinct reversal leg IDs, account/UIC scoping.
2. Enabled V3 manual-seeded trailing LIVE route with reduce-only guard: PR #569, merged `e123e8f92eea56b7f148511070b55db38b3e73e3`. `autotrader_v3_strategy_registry_v1.py` enables trailing route; `autotrader_v3_live_runtime_v1.py` allows only `REDUCE` or `CLOSE` not exceeding actual inventory; source-contract tests updated.
3. Production Saxo precheck repeatedly rejected fractional precision: Norwegian response `Antall desimaler for brøkbeløp overskrider den konfigurerte verdien.` No order was sent by those rejected prechecks. PR #570 **merged** `e0940eb8bcc3e3980d69d605879214b713ad7620` floors trailing reduction amount to 0.01 step with `Decimal(...).quantize(Decimal("0.01"), rounding=ROUND_DOWN)` before precheck; skips sub-0.01 orders. Regression test `tests/test_v3_saxo_order_step_v1.py`. All branch CI and main CI green (main run 36643238403).
4. All **four** Railway services on commit `e0940eb8bcc3e3980d69d605879214b713ad7620`, deployment status SUCCESS verified: worker `f7c32791-44fa-4633-905f-022699521230`, stream `60c1d171-7a08-44a6-b48c-1c253c461269`, web `ad7106dd-53a6-423c-abe2-0fd5c6845966`, trade engine `db374d73-e234-4d90-9b7e-19c8dfbe9997`. Railway project `482dad8f-efc5-415a-b1f7-99f45cb2bd7b`.
5. **Post-deploy first V3 LIVE order submission confirmed by worker log** 23:17:27 UTC, BUY 0.01 reduce short, pilot `b6008676-ec57-50e9-9cbf-3b0577c643ab`. Do not claim fill without broker audit or screenshot.

## Current blocker: order reconciliation

User's screenshot after first live submission: `LIVE BLOCKED: Order reconciliation unavailable: RuntimeError` with timestamp near 23:27 UTC. Worker cycles continue, but no further orders while pending lock exists. `autotrader_v3_live_runtime_v1.py` catches exception around `reconcile_pending_v3` and stores only `type(exc).__name__`, **hiding actual error message** from UI; improve diagnostics safely (no secrets).

Likely code path: `autotrader_v3_order_reconciliation_v1.py` -> `fetch_exact_order_audit_v3` in `autotrader_v3_order_audit_v1.py`. Audit GET `cs/v1/audit/orderactivities` with AccountKey, ClientKey, EntryType All, FromDateTime/ToDateTime last two days, `$top=500`. It raises `RuntimeError('Saxo audit incomplete: cannot reconcile order')` if response Data not list, len>=500, `__next` or `Next`. But RuntimeError could also come from `_position_observations_v2` or other path; **instrument the exact exception before guessing**. Potential audit pagination/endpoint response issue; inspect read-only payload shape and HTTP error, do not log credentials or full personal account data.

`verified_order_fills_v3` currently requires unique `LogId`, exact OrderId/AccountId/Uic/AssetType/BuySell, `PartialFill`/`FinalFill` and FilledAmount, at least one FinalFill, sums fills. Validate Saxo real audit semantics (some statuses might differ, FinalFill amount cumulative vs incremental). `reconcile_pending_v3` also requires fresh exact position inventory equal to expected inventory. AccountKey and ClientKey are fetched from `port/v1/accounts/me`. It marks guard RECONCILED only when all checks pass.

## Next architect's exact steps

1. Read `docs/AEN_V3_LIVE_SAXO_HANDOFF_2026-09-30.md`, `autotrader_v3_live_runtime_v1.py`, `autotrader_v3_order_audit_v1.py`, `autotrader_v3_order_reconciliation_v1.py`, `autotrader_v3_order_guard_v1.py`, `autotrader_risk_control_v2.py`.
2. Query current Railway worker logs (deployment above), filter around 23:17–23:35 UTC. Check whether a detailed traceback for reconciliation exists. UI screenshot reports RuntimeError; code swallows detail, so likely add narrow sanitized diagnostics if logs insufficient.
3. Add read-only observability to expose which reconciliation phase fails (audit request/response shape, pagination, audit row verification, fresh position read, exact inventory mismatch). Preserve pending order lock until independently confirmed. Distinguish exception vs incomplete data vs fill mismatch vs inventory mismatch in runtime status.
4. Fix confirmed root cause, write unit tests with realistic Saxo payloads, run full GitHub CI, merge PR, verify all Railway services deployed to new SHA. Watch worker logs for successful RECONCILED status. **Never force-clear pending orders merely to make UI green.**
5. Once reconciled, confirm latest Saxo position and any subsequent reduce-only order. If user manually changed inventory in Saxo after the first order, expected inventory may differ; handle explicitly without duplicate trades.
6. Review risk of repeatedly triggering rejected prechecks and repeated closed-bar decisions, and ensure V2 and V3 are not simultaneously managing same account+UIC.
7. UI screenshot also showed Engine V3 ON and SHORT, status blocked. Consider clearer presentation of last submitted broker order and reconciliation state.

## Core execution details

`run_v3_live_cycle_v1` runs in `worker.py`. Active enrollments require `EXECUTION_MODE_LIVE` and `live_authority_armed_v3`. It fetches Saxo positions, account map, closed 5m MACD observations from canonical bars, `evaluate_strategy_bar_v3`, then `plan_execution_v3`. Trailing only accepts REDUCE/CLOSE; precheck -> durable reserve -> POST -> SUBMITTED. Next cycle reconciles pending before new signal. On pending reconciliation exception it writes BLOCKED and continues; no second order should be sent.

Do not confuse successful GitHub CI, Railway SUCCESS, Saxo POST acceptance, broker fill, and verified inventory: these are **five separate milestones**. First three are confirmed; fill and reconciliation are NOT confirmed.
