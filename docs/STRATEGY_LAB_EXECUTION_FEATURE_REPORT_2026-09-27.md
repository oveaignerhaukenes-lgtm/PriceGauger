# Feature Report — Strategy Lab execution planning and isolation
Date: 2026-09-27
Branch: main

## Scope
This round turns Strategy Lab from research/chat-only planning into a bounded execution-planning surface while preserving the existing hardened AutoTrader/Saxo execution lifecycle.

## User-facing result
- Strategy titles are clickable; redundant Open buttons removed.
- Strategy discussion remains persistent per strategy.
- Trade Plans now carry an explicit NOK execution budget and a 0–100% exposure allocation.
- Effective exposure cap is budget_nok * exposure_pct / 100.
- A DRAFT plan requires explicit human approval before it becomes an immutable APPROVED handoff.
- Approved plans expose an Execution Control panel for CLOSE, trailing profit, scale-down and stop-loss intents.
- Strategy chat receives budget/exposure semantics and may propose plan changes, but it cannot claim approval or broker execution.

## Execution boundary
Strategy Lab does not POST to Saxo.
The intended chain is:
strategy thread -> plan_id -> handoff_id -> execution scope -> exact LIVE pilot/account/UIC/asset type -> canonical durable execution lifecycle -> Saxo.

OPEN is deliberately still blocked at the Strategy Lab adapter boundary. The canonical manual-target path currently sizes from pilot equity; it does not yet prove that Strategy Lab budget_nok/exposure_pct is the authoritative end-to-end sizing cap. strategy_execution_adapter_v1.require_live_open_budget_support_v1 therefore fails closed with STRATEGY_LAB_LIVE_OPEN_BLOCKED_BUDGET_NOT_END_TO_END.

Do not remove this gate until budget_nok * exposure_pct is carried into canonical OPEN sizing and Saxo precheck, and tests prove no request can exceed it.

## Thread isolation
Each approved plan has immutable scope_id = strategy_key:plan_id.
The adapter scope additionally binds:
- handoff_id
- pilot_key
- account_id
- UIC
- asset_type
- budget_nok
- exposure_pct

No fallback by display name, market name or strategy family is permitted.
Cross-scope controls fail with RESEARCH_EXECUTION_SCOPE_MISMATCH or EXECUTION_ADAPTER_SCOPE_MISMATCH.

A 15-thread test matrix was added: each scope accepts itself and rejects every crossed scope. Single-field mismatches for strategy, plan, handoff, pilot, account, UIC and asset type also fail closed.

## Durable stores
research_trade_plan_store_v1.py
- repaired schema/model consistency
- budget_nok and exposure_pct
- APPROVED handoff snapshot
- scope_id backfill for existing handoffs
- assert_research_scope_v1

strategy_execution_control_v1.py
- durable PENDING management intents
- CLOSE, TRAILING_PROFIT, SCALE_DOWN, STOP_LOSS
- all reads/writes require exact plan + strategy + scope

strategy_execution_scope_v1.py
- immutable adapter identity contract
- max_exposure_nok helper
- all identity dimensions must match

strategy_execution_adapter_v1.py
- validates handoff identity and exact active LIVE enrollment/product boundary
- intentionally blocks OPEN until budget is end-to-end authoritative

## Factors added to gold research strategy
- credit spreads/stress
- equity buybacks
- equity flows / margin debt
- system liquidity
- VIX / option skew
- funding / repo stress
- GLD/SLV / CFTC flows

## Safety invariants
1. Chat has no broker authority.
2. DRAFT has no execution authority.
3. APPROVED is immutable handoff data, not a broker order.
4. Exact scope match is mandatory.
5. Exact active LIVE pilot/account/UIC/asset type match is mandatory.
6. One mismatched identity field blocks execution.
7. CLOSE/risk-reduction must not depend on unused entry budget.
8. OPEN remains blocked until Strategy Lab budget is enforced by canonical sizing/precheck.
9. No second direct Saxo POST path may be introduced.

## Tests added/extended
- tests/test_strategy_execution_scope_v1.py
  - 15 simultaneous isolated scopes
  - all cross-thread combinations rejected
  - single identity mismatch rejected
  - budget/exposure local to scope
- tests/test_strategy_execution_adapter_v1.py
  - OPEN budget safety gate must remain closed
- tests/test_research_trade_plan_v1.py
  - approval boundary
  - budget/exposure wiring
  - scoped controls
  - regression check for stale key variable/import corruption

## Important fixes made during this round
A partially applied earlier budget patch left research_trade_plan_store_v1 inconsistent and Strategy Lab had stale call signatures plus an undefined key variable in execution controls. These were repaired before the adapter work continued. Treat commits before the repairs as superseded by current main.

## Railway status observed during implementation
- commit bacf83e40bfff1a26227b691c5b6b655239da3f3 (15-thread isolation tests) deployed SUCCESS.
- subsequent UI/adapter/test commits entered normal Railway build/deploy queue.
Verify latest main deployment before enabling or changing execution authority.

## Main commits in this feature round
- dfe0ac4 — clickable Strategy Lab titles
- 56c9de5 — repair trade-plan schema + execution scopes
- 5a96cc1 — fail closed on cross-thread controls
- 06507b4 — bind UI controls to execution scope
- 39c62a5 — immutable adapter scope
- bacf83e — 15-thread isolation tests
- 207518b — repair Strategy Lab budget/scoped control wiring
- f398f56 — fail-closed execution adapter boundary
- bb89a9a — OPEN budget safety-gate test
- 78c9281 — Strategy Lab scoped wiring regression test

## Next architect: recommended next work
1. Verify latest Railway web deployment and runtime logs after current main.
2. Run the relevant pytest suite in CI/local environment.
3. Build one canonical budget-aware OPEN API below Strategy Lab, not a new broker path:
   - input must include immutable scope
   - resolve exact active enrollment
   - cap notional to max_exposure_nok
   - pass the same cap into sizing and Saxo precheck
   - persist request provenance back to plan_id/handoff_id/scope_id
   - only then change live_open_budget_supported_v1 to True.
4. Add consumer/ack state for management intents (PENDING -> ACCEPTED/EXECUTED/REJECTED) and bind each result to canonical execution request IDs.
5. CLOSE should reuse autotrader_manual_close_v1 after exact observation/product resolution.
6. Trailing/scale-down/stop-loss should reuse existing canonical risk/position-management modules where available; do not create direct UI broker calls.
7. Add notification events after durable state transitions (approval required, queued, filled, rejected, stop/invalidation). PG push first; Gmail may consume the same event stream.
8. Once end-to-end tests pass, update docs/CURRENT_STATUS.md and expose explicit UI state such as READY / BLOCKED(reason) / QUEUED / LIVE / CLOSED.

## Definition of done for LIVE promotion
Do not call Strategy Lab LIVE-capable until an integration test proves:
approved plan -> exact scope -> exact LIVE enrollment -> capped sizing <= max_exposure_nok -> canonical precheck -> durable request -> broker attempt/reconciliation,
and a crossed scope cannot create, mutate, close or manage another thread's position.
