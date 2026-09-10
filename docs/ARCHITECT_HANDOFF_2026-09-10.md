# PriceGauger architect handoff — 2026-09-10

## Current live context

PriceGauger is actively managing US Tech 100 NAS (Saxo UIC 4912) with the simple AutoTrade contract. The active pilot seen in live logs is using `macd-2m-flip-control-shadow-v1`. The intended invariant is state reconciliation, not edge-only execution:

`desired LONG/SHORT -> compare exact Saxo product state -> CLOSE opposite exposure -> confirm Saxo FLAT -> OPEN desired side`.

`Manage position` owns/adopts the exact Saxo product state. `AutoTrade` enables autonomous strategy reconciliation. Manual BUY/SELL are overrides routed through the same execution-request lifecycle.

## Safety invariants — do not weaken

- One active LIVE controller per exact product.
- Exact product identity = account + UIC + AssetType (+ direction where admission requires it).
- No one-order reversal. Always CLOSE -> confirmed broker FLAT -> OPEN opposite.
- SUBMITTING/UNCERTAIN close state blocks re-entry.
- Durable attempt before broker POST; never blindly retry uncertain submit.
- Final precheck immediately before POST.
- Position Guardian/RiskControl is defensive only and may never originate/increase exposure.
- Pilot capital is isolated from unrelated Saxo cash. `MAX_WITHIN_PILOT` means all available pilot equity within the margin envelope, not all account equity.
- Realized-P/L accounting is not execution authority and must not sit on the critical reversal path.

## Incident on 2026-09-10

A live screenshot suggested missed MACD flips. Stream logs showed the signal/runtime layer was actually healthy and repeatedly observed:

`observed=SHORT desired=LONG pending=LONG reason=PENDING_TRANSITION_RETRY_READY`

So the fault was downstream of signal generation. At the same time, `autotrader_closed_position_reconciliation_v2` emitted a burst of Saxo `HTTP 429 Rate limit exceeded` errors while resolving old `OrderActivities` provenance. The reconciliation thread was polling every 5 seconds, re-reading the same historical backlog, and its in-cycle cache was discarded on every cycle. This could consume Saxo GET capacity needed by live execution.

The Saxo net-position payload also showed `Amount=-0.01`, `AmountLong=0.14`, `AmountShort=0.15`. PG correctly resolves the net direction to SHORT. Do not infer from those aggregate fields alone that 29 simultaneously open legs exist; investigate Saxo semantics before changing position logic.

## Current bounded fix

Branch: `autotrader/reconciliation-backoff-v2`

The change keeps the execution/state-machine architecture and simplifies the accounting runtime rather than stacking another execution workaround.

`autotrader_closed_position_reconciliation_v2.py` now:

- processes at most one unresolved reconciliation candidate per cycle;
- enforces a minimum 15-second accounting cadence even if an old env var requests 5 seconds;
- applies retry backoff of 30s -> 120s -> 10m -> 30m -> 60m;
- caches Saxo account context for 5 minutes;
- caches only positive immutable OrderId -> PositionId provenance results;
- does not cache empty provenance results, because Saxo settlement may simply be late;
- logs deferred accounting explicitly;
- preserves exact provenance requirements and never falls back to time/price/direction inference;
- leaves the existing execution/accounting decoupling intact: OPEN authority is based on broker-flat execution provenance, not realized-P/L settlement.

Tests added in `tests/test_autotrader_reconciliation_backoff_v1.py` lock the retry schedule, one-candidate budget, due-time behavior, state clearing, and deliberately slower accounting cadence.

Important limitation: the retry/backoff state is process-local. That is intentional for this bounded fix; restart may retry a historical item once, but one-candidate-per-cycle + 15s minimum cadence prevents a restart storm. If persistent retry scheduling is later needed, add it as explicit accounting state rather than coupling it to execution tables.

## Related architecture already on main

`autotrader_live_open_v2.py` is a facade around the preserved hardened legacy executor. It already decouples execution provenance from P/L accounting: ORDER_ACCEPTED/RECONCILED close provenance plus independently observed exact Saxo FLAT is enough to permit re-entry, while SUBMITTING/UNCERTAIN remains ambiguous and blocks. Do not restore the old requirement that an equity-reconciliation row must exist before re-entry.

The simple MACD runtime is level/state driven: spread > 0 => desired LONG, spread < 0 => desired SHORT. Cross labels are diagnostic transitions, not the only source of authority. Terminal BLOCKED/REJECTED requests may safely re-arm for the current level target; UNCERTAIN/SUBMITTING/ORDER_ACCEPTED/SUPERSEDED are not blindly revived.

## Recent UI work

PR #357 landed chart BUY/SELL controls through the existing manual-target path and fixed chart continuity so normal Streamlit refresh should preserve the existing Lightweight Charts instance instead of destroy/rebuild. PR #358 compacted the chart BUY/SELL controls for mobile. If visual regressions remain, keep them separate from execution work.

## Pilot capital model

Seed is 500 NOK. Pilot status recently showed equity around 666 NOK / +33% realized, while Saxo account value was around 719 NOK. The difference should be explained by open P/L, accruals/costs, and/or value outside the settled pilot ledger. A future UI reconciliation line showing Saxo account value vs pilot equity would improve transparency.

Compounding is already active: live OPEN reloads current settled pilot equity and sizes against that controlled-capital margin envelope. Harvesting is not implemented. Agreed future policy: no harvesting until capital-lineage equity reaches 2x original seed; afterward harvest 20% of positive settled realized profit into a logically separate reserve. Never harvest unrealized P/L and do not add broker-transfer authority without an explicit separate mandate.

## Known non-blocking issues

- OpenAI API quota is currently exhausted in production, so AI baseline/news scoring logs 429 insufficient quota. This should not affect the simple MACD execution path.
- Natural Gas has stale/failed data and rollover/warmup errors; keep it fail-closed.
- S&P Cocktail still reports invalid 5m ATR. Do not paper over this with zero/min ATR.
- Some legacy frontend debug chrome (`unknown · unknown`, `Sigma Signalaggregat`, `Stop`) may still remain.

## Next steps for the next architect

1. Finish CI/review/merge/deploy for the reconciliation-backoff PR if not already complete.
2. After deploy, inspect STREAM logs during the next real 2m reversal. Success criterion: desired != observed results in CLOSE -> broker FLAT -> OPEN opposite without a reconciliation 429 storm.
3. Verify that background P/L settlement can lag without blocking reversal and that later settlement still updates pilot equity exactly once.
4. If reversal still stalls, inspect strategy CLOSE/live OPEN lifecycle states and Saxo rate-limit responses before changing signal logic.
5. Separately investigate Saxo `AmountLong`/`AmountShort` aggregate semantics; do not modify exact net-direction logic based only on those fields.
6. Once execution is stable over time, return to pending product work: experimental `5m MACD + Price Structure + Impulse Override`, chart/mobile polish, and account-vs-pilot reconciliation display.

## Working style

Prefer bounded PRs. Inspect current `main` before modifying execution. Keep safety invariants explicit in tests. Merge only with green CI and verify Railway production after merge. Avoid architecture rewrites for cleanliness alone; rewrite a subsystem only where a simpler contract materially reduces runtime coupling or failure modes.
