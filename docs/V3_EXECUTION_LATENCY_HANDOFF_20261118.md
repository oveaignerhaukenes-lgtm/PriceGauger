# V3 LIVE latency and predictability — handoff, 2026-11-18

## Objective

User priority: **predictable execution latency / low P95 and P99**, not merely lower mean.
Do not deliberately slow fast orders to equalize latency. Desired technical target
(signal -> Saxo POST attempt, *not confirmed fill*): median <1s, P95 <2s, P99 <3s.
These are goals, **not achieved**. Never conflate LIVE Saxo acceptance, confirmed fill,
quote event timestamp, or worker queue time.

## Implemented and verified (chronological)

- PR #853 (2026-11-18): per-account parallel V3 worker routing; one active task per Saxo account; quote-only wake paths; recheck stale entry signal before Saxo POST. CI green and Railway deployed.
- PR #854: 15-second **account + bearer + UIC scoped** cache for broker-validated LIVE reference instrument rules; per-cycle verified account identity reuse; LIVE REST GET/POST and HTTP 429 counters. No account position / order cache.
- PR #855: bounded read-only phase timing (account GET, exact inventory, instrument rules, decision, modifiers, entry cost illustration, capital sizing, precheck, POST). HTTP POST telemetry distinguishes precheck and orders.
- PR #856: early stale quote OPEN/ADD veto before Saxo cost/precheck, retaining both later freshness vetoes and all REDUCE/CLOSE paths.
- PR #857: V3 account-worker-only psycopg_pool connection reuse (bounded max 12, checkout timeout 3s, checked connections, commit/rollback before return; unsafe writes never retried). P50/P95/P99 timing; decision-to-POST and quote-to-POST measurements. SIM, SQLite, other PG workers/UI not pooled.
- PR #858: read-only bounded SQL read/write/finalization timings and full-account-cycle measurements. Logs contain only aggregate phase timing, not raw SQL or credentials.
- PR #859: on PostgreSQL, initialize closed-bar driver (4 tables), LIVE runtime status, and V3 decision-context schemas transactionally once per DB identity and process, not each account cycle. All runtime status/context UPSERTs still happen on every evaluation; SQLite retains old self-initializing semantics. CI green.

**Last checked production Railway worker deploy:** commit `2fcacb9ba891`, status SUCCESS, 2026-11-18 about 22:39 UTC. Six V3 instances still discovered and worker starts; no account-cycle failure observed in checked post-deploy window. No trader strategy, live arming, position, account boundary, broker order, precheck, loss guard or pending lock deliberately changed.

## Grounded LIVE measurements (not apples-to-apples formal benchmark)

Before the pool and schema changes:
- Impulse Catcher observed signal->Saxo accepted POST lag: ~13s entry, ~38s exit in a specific user-reported sequence; other observed outliers >50s. These include signal event-to-Saxo response, NOT confirmed Saxo fill.
- Per-account cycle warnings at times >15-25s; signal/decision phase commonly ~0.8-1.5s with isolated 5-10s outliers.
- One entry cost_guard call measured **11.125s**; the corresponding precheck ~0.351s.
- 2026-11-18 21:01 UTC: at least one Saxo HTTP 429 came from `trade/v2/orders/precheck`, not actual order POST. HTTP 429 may recur.

Pool, first 60s at ~22:20 UTC:
- `db_acquire` n=272, **P50=1ms, P95=24ms, P99=93ms**, maximum 153ms.
- Subsequent minute at ~22:24 UTC: checkout P50=1ms, P95=11ms, P99=37ms.
- BUT account cycles remained highly variable; pool checkout improvement alone did not fix execution.

With detailed SQL instrumentation, pre-#859:
- ~22:29 UTC: `db_write` n=300 sample-cap, `db_read` n=138 P99=1.043s; `account_cycle` n=6 P95=5.037s.
- ~22:30 UTC: `account_cycle` n=6 P95=25.229s; a single `instrument_rules` phase reached **16.366s**. `db_read` P99=0.867s.
- The 60s phase sample buffers cap at 300 per category; n=300 means **at least 300**, not exactly 300 operations/min.

After #859:
- ~22:39:59 UTC: `account_cycle` n=7 P95=15.173s; `db_acquire` P95=14ms; `db_read` P99=0.864s; `db_write` hit 300 sample cap.
- ~22:41:00 UTC: `account_cycle` n=11 P50=25.302s, P95=25.304s; `accounts` P95=5.255s; `db_read` P99=0.994s; `db_write` hit 300 sample cap.
- Small account-cycle n means P95/P99 are **descriptive observations, not stable population estimates**.
- `account_cycle` measures submit-to-future-collected by the worker polling scheduler; it may include worker loop blockage/queueing, not only actual in-account execution.

**No evidence yet that end-to-end stable 1–3s execution goal is met.**

## Next priority

1. **Distinguish scheduling delay vs running account task**: record worker-loop tick drift, task started/finished monotonic timestamps *inside* each worker, completion/collection lag, and per-account queue backlog P50/P95/P99. Current account_cycle timings can be inflated by stalled scheduler.
2. **Measure Saxo network RTT per endpoint** independently of strategy phases (account listing, NetPositions, ref details, infoprices, costs, precheck, live order). No extra API calls. Track 429 and remaining quotas; never conflate POST response with filled execution.
3. **Reduce DB mutations/read round trips:** many DB write queries per full cycle even after schema-once, frequently >=300 sample cap/min; identify table or operation classes via sanitized counters, avoid repetitive DDL and unchanged state writes only where heartbeat semantics remain intact.
4. **Make fresh signal evaluation independent of slow broker account reads** while keeping verified exact-account inventory, durable unique order reservation, confirmed pending order reconciliation, current live arming, and fail-closed risk checks. Priority exit/reduction path must not be blocked by low-priority cost/reference GETs. This is a substantial architecture task; first use isolated tests/replay and do not bypass broker precheck without explicit safety review.
5. Consider proactively refreshing **per-account/token-scoped static instrument rules** before expiry to prevent 16s blocking refresh on critical path. Do not silently trust stale IsTradable for risk expansion; guard with broker-authoritative precheck and fresh source.
6. Analyze actual order event logs for signal timestamp -> decision -> Saxo POST attempt -> broker ACK -> confirmed fill; compare distributions separately for entry and exit and across all six accounts.

## Deployment procedure / safeguards

- Preserve all live strategy/account settings, existing pending locks, exact Saxo account identity, local ownership checks, duplicate-order protection, late OPEN veto, reset-on-loss and account loss guard, position reconciliation, order precheck, and manual Saxo confirmation requirements.
- Push PR -> wait complete GitHub CI -> merge -> check newest Railway worker deploy (docs bot may add a subsequent commit) -> verify runtime logs and explicit commit -> check live errors, HTTP 429, SQL phase tails and P95/P99.
- User prefers self-contained thorough working sessions; do not assume background progress unless an actual scheduled job was created.
