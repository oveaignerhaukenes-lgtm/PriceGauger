# ADR-004 — AutoTrader V4: local-first, Saxo-first, outcome-first
Status: **proposed architecture / isolated prototype** (2026-10-21).
This is a replacement *design*, not authorization for a LIVE cutover.

## Decision
Build a new application centered on **AutoTrader and the exact Saxo account**. Do not lift the V3 database/schema/runtime wholesale onto a new machine. Keep PriceGauger V3 and its PostgreSQL data read-only/archived as audit history until an explicit, verified cutover. V4 gets a **separate database, container namespace, secrets and execution authority** from day one.

### Why
The purpose of the product is to find out *which strategy increases reconciled Saxo account value, under which market conditions*, and to trade only through durable controls. Forecasts, context, broad news, research shadows and AI should not be prerequisites of a reliable trader. Streamlit UI/history re-renders and massive cross-market polling belong outside the hot loop.

## Concrete module boundaries
```
Saxo LIVE / SIM account & product identity
  -> saxogw: OAuth2/refresh, subscribe BBO, account / position / order / fills GET
  -> ingest: fresh in-memory quote ring + 1m completed bars on subscribed instruments
  -> pure strategy: versioned strategy model, signal, intent and evidence timestamp
  -> policy: equity/margin cap, sizing, stale feed, risk, explicit arming gates
  -> execution: durable reserve -> precheck -> broker POST -> reconcile / UNKNOWN
  -> ledger: account NAV, signed fills, booked funding/cost/FX/cashflows
  -> attribution: realized after-cost P/L, intervals, strategy x regime
  -> FastAPI: authenticated, read-focused Fleet / TradingDesk / StrategyLab
             Never holds broker order privileges by itself.
  -> future plugins: macro/news/AI/regime models; evidence only until separately approved.
```

### Runtime separation (one home Linux host initially)
- `at4-saxo-collector`: SaaS REST GET + stream; scoped broker tokens stored only on server.
- `at4-executor`: *singleton* order authority, separate process, explicit account-level lease and durable intent/order state, disabled and not even started in milestone 1.
- `at4-reconciler`: broker GET of positions/orders/transactions, facts and gaps. Never assumes network timeout = failed order.
- `at4-telemetry`: balance every 5 minutes, official EOD records and cashflow/funding reconciliation.
- `at4-api`: private control/read API and later web UI; no independent broker order tokens.
- `at4-db`: PostgreSQL with bounded pool; writes indexed by exact Saxo account/UIC/asset type/event time.
- Optional `at4-lab` comes after factual LIVE measurement; deterministic replay with isolated paper ledger.
- No Redis until measurements justify it; short lived quotes can stay in memory and be snapshotted when a decision is made.

### Use vs rewrite
**Re-use semantics/tests, not necessarily old modules:** exact Saxo account/Product identity; OAuth renew; verified LIVE endpoint; quote freshness, min size, cost/margin precheck; durable idempotent order reservation; UNKNOWN state and Saxo reconciliation; account ownership; CLOSE -> confirmed FLAT -> fresh OPEN; historical account and execution records; limits, arming and audited failure states.
**Rewrite in narrow modules:** database adapters (pool + managed migrations); strategy plugin interface; signals and read models; UI and data capture; process health checks.
**Do not bring forward initially:** wide forecast/Companion/Telegram/news pipelines, 100 always-on strategy variants, global 1s DB polling, perpetual tick-level historical storage, full legacy schema/Streamlit.

## Minimal persistent truth; new DB (see `autotrader_v4/schema/001_core.sql`)
1. `accounts` and `instruments`: exact Saxo identity, currency and product, no implicit cross-account / cross-UIC alias.
2. `strategy_assignments`: *append-only* effective event with strategy **version + parameter digest**, account, instance, instrument, options, armed vs actually executing. Strategy effective time is never guessed from a five-minute account snapshot.
3. `market_bars_1m`: canonical closed OHLC (with strict OHLC integrity), exact UIC/asset type; optional verified provider volume and source timestamps. 1s BBO is an **ephemeral ring**, not permanent 24/7 DB traffic. At each decision, persist the exact observed BBO and freshness in `strategy_decisions`; permit short bounded raw-tick retention for investigating 10s engines, only if needed.
4. `strategy_decisions`: immutable decision time, causal data cutoff, strategy/config version, desired delta, BBO, reason/ignored reason. Provenance is as important as fill performance.
5. `order_intents` and `broker_order_events`: durable idempotency key, exact account/UIC/asset type, state machine, broker order IDs, timestamps and reconciliation. UNIQUE unresolved boundary **in SQL**, not only Python.
6. `broker_fills`, `account_snapshots`, `cashflows`, `broker_costs`: distinct broker facts, no guessed spread/FX/funding, stable unique source IDs. Store monetary amounts with exact currency and NUMERIC, never sum NOK/USD without verified conversion.
7. `regime_snapshots` **optional late**: deterministic, versioned derived features (slope/realized volatility/chop/whipsaw/session). As-of evidence time <= decision time, source UIC + lookback, never future bars.

**Derived, not redundantly stored each second:** indicators, curves, rankings, per-regime win rate/after-cost P&L. Derive from durable facts and bounded caches. PAPER and LIVE always distinct source namespaces.

## Risk and outage policy
- Read-only first; no broker POST route in V4 until explicit account-specific LIVE approval after end-to-end reconciliation tests. Never migrate arming flags or credentials from V3.
- For **any** uncertain POST, state becomes UNKNOWN; do not retry blindly. Broker reconciliation and account inventory are authoritative.
- Fail closed for *new* OPEN/ADD on stale BBO, bad token, disconnected Saxo, budget/margin uncertainty, missing DB transaction, position discrepancy or duplicated executor lease. Existing positions may remain exposed during network/power outage; a home machine cannot guarantee emergency close. Where supported, independently verified broker-native protective orders should be considered, but not assumed.
- Exactly one authorized executor **across Railway V3 and local V4**, not simply one container per deployment. Cutover requires Railway/V3 authority revoked, all unsettled order states and broker inventory verified, then explicit activation of one bounded V4 Saxo account. No automatic failover second writer.
- API/control panel, lab, context models, CI, external cloud backup, and server management have no access to Saxo order token by default.
- Do not expose Postgres, SSH, Coolify or executor port on public Internet. Use Tailscale for administration and a separate authenticated web exposure if needed. Never submit SSH keys, API tokens or passwords to chat/GitHub.

## Hardware / operations
Host: i7-7700K (4 cores/8 threads), 16GB RAM (32GB optional later), 256GB SSD, 4TB data disks, 500/500 Mbit fiber, CAT6.
- Ubuntu Server LTS + Docker Compose for reproducible V4; optional Coolify as deployment dashboard once core infrastructure is proven.
- SSD: OS, PostgreSQL active data/WAL and live containers. 4TB: **only after identifying drive filesystem/redundancy** for archives and local backups; storage must not be mistaken for independent offsite backup.
- Encrypted offsite PostgreSQL backups + tested restore; UPS, network equipment battery, on-host metrics and alerts.
- GitHub Actions builds/tests immutable images; local host pulls pinned image digest after successful CI and explicit promotion; avoid self-hosted CI runner with general repo write privileges on the trading host.
- A minimal remote management agent may execute *allowlisted* read-only healthchecks and signed deploy operations. The ChatGPT integration currently has no direct SSH terminal; it can author PRs and release artifacts, but actual host commands require a user-controlled bridge.

## Delivery milestones / acceptance gates
M0 **Infra:** Ubuntu, Tailscale, Docker, SSD layout, offline backup, test restore, GitHub CI. NO Saxo auth. Server reboots and relaunches cleanly.
M1 **Read-only Saxo:** OAuth, exact account + position/order snapshots and BBO streaming for a single chosen product; read-only DB ingest. Verify provider timestamps/delay/staleness and reconnection. No order POST code in the running service.
M2 **Account truth:** official EOD, 5m TotalValue, complete paginated transactions/costs/cashflows, normalized execution and position ledger; show verified/unverified provenance.
M3 **Paper/strategy:** one simple baseline + existing MACD5/Hunter/Rabid as separately **ported and replay-verified** strategies; per-decision evidence/cost-inclusive paper results, no hindsight, reproducible restart.
M4 **Controlled LIVE:** first a single bounded account, explicit separate arming, broker precheck, reservation, unknown-state safety, reconciliation and hard risk limits; observe broker fills for multiple active sessions. Old engine confirmed not authorized to control same account. Rollback requires broker-truth reconciliation, not just a redeploy.
M5 **Ranker/UI:** compare strategies x verified market regime using actual after-cost broker ledger and sample-size/uncertainty, optional small StrategyLab; then add context/news/AI if incremental value is shown.

## Proposed first implementation PR
Architecture ADR plus **standalone zero-privilege V4 domain model, schema and tests** in `autotrader_v4/` only. No edits to app navigation, Railway start commands, V3 runtime/DB, or enabled trading flags. The new module must have no import from old LIVE order code or any Saxo POST dependency.

## Scope note
Existing Railway 20GB PG PostgreSQL is intentionally *not* copied or erased. Once V4 starts, its analysis history begins anew; optionally preserve old broker-account and execution data offline for comparison, with separate independent backups before any destructive action.
