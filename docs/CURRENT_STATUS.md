# PriceGauger — Current Status / Stable Checkpoint

**Status date:** 2026-08-30  
**Stable checkpoint runtime baseline reviewed:** `fe0949437cf967ef526465ae8044131b87d1cb22`  
**Latest post-checkpoint production cleanup verified:** `95b4c64cf00851caf06e2c9ccb3a2505e978e424`  
**Purpose:** authoritative implementation status for the next development handoff.

This file is the current status authority. `PRICEGAUGER_V2_ARCHITECTURE.md` and `PRICEGAUGER_V2_SYSTEM_OVERVIEW.md` remain architectural references. Older handoff files are historical and must not be used to infer current implementation status without checking this file and fresh `main`.

## Post-checkpoint cleanup — 2026-08-30

The architectural feature-freeze checkpoint remains the `#239` checkpoint built on the reviewed `#238` runtime. Two observability-only cleanups landed afterward without changing strategy, risk, order, P/L, database or execution semantics:

- `#240` added split Python logging and observer-only RiskControl warning throttling. Production verification showed that Railway did not invoke the implicit `sitecustomize.py` hook, so the code was present but not applied.
- `#241` made application explicit through a tiny Railway runtime launcher while leaving `realtime_worker.py`, `telegram_multi_worker.py`, AutoTrader and RiskControl logic unchanged.

Production verification on `#241` / `95b4c64cf00851caf06e2c9ccb3a2505e978e424` showed:

- web, worker and stream all `SUCCESS`;
- normal Python `INFO` from stream/worker is now Railway severity `info` rather than false `error`/stderr noise;
- a real `WARNING` remains on stderr;
- the first observer-only `eligible=False` RiskControl warning remains visible, while identical repeats are suppressed for five minutes;
- the RiskControl portfolio cycle continues on its unchanged cadence and continues reporting the latched close signal as INFO, confirming that only log emission changed.

## Stable-point conclusion

PriceGauger has reached a coherent v2 production baseline. The major runtime subsystems share canonical market/instrument identity and PostgreSQL state, the deterministic Technical Core is live, the context/forecast stack is persisted and inspectable, TradingDesk consumes the v2 market context, and AutoTrader now has a bounded autonomous execution path with explicit independent authority gates.

The project is suitable for a **feature freeze / observation checkpoint**. New work should start from fresh `main`, one bounded capability per PR. Do not reopen old feature branches into this baseline.

This checkpoint does **not** mean every analytical model is mature or that autonomous trading has been proven with meaningful real-money history. It means the architecture and production runtime are coherent enough that further development can be evaluated against a known baseline instead of continued migration.

## Production / Railway

Production is split into three services plus PostgreSQL, all sourced from `oveaignerhaukenes-lgtm/PriceGauger` branch `main`:

| Service | Responsibility | Current state |
| --- | --- | --- |
| `pricegauger-web` | Streamlit UI / read-render / TradingDesk | SUCCESS |
| `PriceGauger-worker` | Telegram/news ingest, context/state publication, forecast-related work | SUCCESS |
| `PriceGauger-stream` | Saxo realtime/canonical market runtime, Technical Core, AutoTrader daemons | SUCCESS |
| PostgreSQL | shared authoritative persistence | SUCCESS |

The reviewed `#238` execution-sensitive checkpoint deployment corresponds to `fe0949437cf967ef526465ae8044131b87d1cb22`. The later observability-only deployment verified in production corresponds to `#241` / `95b4c64cf00851caf06e2c9ccb3a2505e978e424`.

Observed runtime at checkpoint and post-checkpoint verification:

- no `Traceback` found on web, worker or stream after the reviewed deployments;
- stream heartbeat/reauth/gap-repair continues;
- Technical Core cycles observed `attempted=7 produced=7 failed=0`;
- MACD dry-run cycles observed `attempted=7 evaluated=7 failed=0`;
- worker continues Telegram/news ingest and context publication;
- a `STALE` Context v2 snapshot on the Sunday checkpoint is fail-stale behavior, not evidence that the worker stopped. Freshness must be judged against market/reference availability rather than worker liveness;
- Railway severity now reflects Python severity for the long-running worker/stream services.

### Railway deployment-policy caveat

Railway source configuration currently has `checkSuites=false`. The project workflow therefore continues to enforce CI-before-merge at the GitHub/PR process level. If Railway check-suite gating is changed later, treat that as a bounded deployment-policy change and verify that it does not disrupt the existing deploy flow.

## CI baseline

The last execution-sensitive PR before the stable checkpoint (`#238`) ran:

```text
python -m compileall -q .
python -m pytest -q
```

Result: **910 passed, 0 failed**.

The explicit observability follow-up `#241` also passed full compile and repository pytest after its Railway-config contract tests were updated to the new launcher command. Its final suite contained **918 passing tests**.

CI passing is necessary but not sufficient for execution changes. AutoTrader changes must continue to use fresh-main checks, explicit diff/safety review and expected-head merge guards.

## Canonical data and instrument identity

Production identity is dynamic and provider-backed:

```text
provider instrument
→ instrument registry / explicit subscription
→ canonical market + instrument identity
→ canonical 1m observations
→ shared consumers
```

Important properties:

- execution-sensitive consumers use the exact `instrument_id`, not a generic merged market history;
- browser/UI is not the authoritative market-data producer;
- Saxo positions opened outside PriceGauger can be discovered and onboarded to canonical identity;
- newly discovered Saxo products receive deep enough canonical history for 30m MACD rather than waiting many live hours/days;
- missing data remains explicit; no silent synthetic fill should create execution evidence.

At the checkpoint, the externally opened `CfdOnIndex` UIC `4912` is discovered as canonical `US Tech 100 NAS · Saxo 4912` and participates in Technical Core/MACD runtime.

## Deterministic Technical Core

Technical Core remains the control group and deterministic baseline. It is context-blind by design.

It produces versioned state covering trend, momentum, volatility, structure, score/confidence and timeframe snapshots. Technical baseline forecasts are persisted with deterministic identities. This layer must remain usable when every optional context/AI layer is removed.

Do not move news, macro, Companion or execution logic into Technical Core.

## Workspace, forecasts and learning

The v2 workspace composes one coherent market/as-of technical state, technical baseline forecasts and optional cached layers. Layer outputs are tied to the workspace fingerprint so stale outputs cannot silently attach to a different technical snapshot.

Forecast persistence is immutable/idempotent by semantic identity. Outcome/evaluation infrastructure exists so recipes/layers can be compared against realized outcomes rather than accepted by narrative plausibility alone.

Current maturity distinction:

- architecture/persistence/runtime loop: established;
- forecast quality/calibration: ongoing product/model work;
- direction/regime learning: deliberately constrained/disabled where not yet empirically justified;
- higher layers must remain removable so TA-only stays the empirical control.

## Context / Companion / cross-market

Context is a separate layer above deterministic technical state. News/Telegram ingestion is live in the worker and Context v2 is persisted with explicit freshness semantics.

The descriptive cross-market/adaptation chain remains conceptually:

```text
CrossMarketState
→ ResponseDivergence
→ TransmissionState
```

It is observational/evidential unless an explicit future recipe grants it forecast influence. It must not silently rewrite Technical Core or execution decisions.

Yield semantics remain strict: US 2Y/10Y/30Y values require a verified yield feed. Treasury futures prices must not be substituted for yields merely to eliminate `MISSING` data.

Companion/AI is decision support. It has no direct order-placement authority.

## Overview and TradingDesk

Overview/TradingDesk are consumers of persisted/canonical v2 state rather than independent sources of truth.

TradingDesk is the human cockpit for charts, technical/forecast/context information and AutoManage controls. It must not bypass AutoTrader execution gates.

Legacy-named adapters still exist where they are proven compatibility boundaries. Their filename/version suffix alone is not evidence of an active second architecture. Remove/rename them only in a bounded refactor with equivalent safety tests.

## AutoTrader — current production capability

AutoTrader is now a separate product/strategy/execution subsystem rather than a close-only experiment.

General model:

```text
AutoManage product container
→ strategy policy
→ durable strategy evaluation / execution request
→ execution/risk gates
→ Saxo precheck
→ persisted attempt before POST
→ Saxo execution
→ reconciliation
→ authoritative realized P/L
→ pilot equity / compounding
```

### Strategies

Supported 30m closed-bar MACD 12/26/9 policies:

1. `macd-30m-long-flat-v1` — bullish cross → LONG; bearish cross → FLAT.
2. `macd-30m-short-flat-v1` — bearish cross → SHORT; bullish cross → FLAT.
3. `macd-30m-long-short-v1` — bullish cross → LONG; bearish cross → SHORT, implemented as CLOSE → confirmed FLAT → OPEN rather than a one-order reversal.

Strategy chooses desired exposure, **not leverage**.

### Entry behavior is independent from strategy

Each LIVE pilot can use one of three entry policies:

- **Manage-only / `MANUAL_ENTRY_ONLY`** — user creates exposure; PriceGauger may manage/close it but never sends OPEN.
- **Full auto / `AUTO`** — eligible fresh strategy OPEN may proceed through all execution gates without another human click.
- **Approval required / `APPROVAL_REQUIRED`** — CLOSE remains automatic; a concrete OPEN request requires one-shot approval and is fully revalidated before POST.

One exact account+UIC+AssetType has at most one enabled LIVE controller. Multiple shadow strategies are allowed.

### Persistent Manage-only

Manage-only is a persistent operating mode, not a one-position attachment. When the user later manually opens, resizes or reverses exposure on the same exact account+UIC+AssetType, the active Manage-only pilot can adopt the new exact Saxo basis before CLOSE execution.

Adoption:

- grants no OPEN authority;
- resets the risk-management epoch;
- updates the managed exact position basis/anchor;
- supersedes stale unstarted strategy requests and pending reversal intent;
- blocks while any PriceGauger OPEN/CLOSE is unresolved;
- fails closed on ambiguous multiple matching positions.

### Risk and CLOSE

LIVE CLOSE retains the hardened path:

- LIVE Saxo environment required;
- deployment code capability plus persisted execution arming required;
- exact managed position identity/basis re-read before execution;
- current tradability/risk re-evaluation;
- Saxo precheck;
- attempt persisted before POST;
- no blind retry after uncertain submission;
- reconciliation after accepted submission.

RiskControl observes the portfolio without thereby gaining execution authority. Enrolling a position starts a **new risk epoch**, so pre-enrollment observer-only high-water/trailing state cannot become retroactively executable. Current hard-stop conditions may still legitimately trigger after enrollment.

### LIVE OPEN

LIVE OPEN is implemented but intentionally fail-closed. Automatic/approvable entry requires all applicable gates, including:

- active LIVE strategy enrollment;
- entry mode/arming authority;
- fresh strategy signal;
- confirmed FLAT product state;
- fresh post-close P/L reconciliation where applicable;
- direction-specific Product Admission;
- Margin Envelope for margin products;
- actual Saxo order precheck and product metadata-based sizing;
- persisted idempotency boundary before POST;
- no blind retry on uncertain submission.

Product Admission is account+exact-product+direction specific. Margin products require explicit safety verification rather than inferred protection.

### Pilot capital / P&L

Pilot equity is isolated:

```text
seed capital + authoritative settled realized net P/L
```

Unrelated Saxo cash and unrealized P/L do not enlarge the strategy budget. Losses reduce future budget; exhausted equity blocks OPEN but must never block a necessary CLOSE.

Closed-position P/L is reconciled against PriceGauger closing external references, supports split closes, and books only when the full close is represented.

### Shadow benchmark

The strategy scorecard compares long/flat, short/flat and flip using deterministic replay over the same canonical path and the same observed enrollment exposure/start point.

The benchmark:

- never bootstraps from historical MACD regime instead of the observed position;
- uses only post-enrollment closed 30m information;
- is read-only and has no order authority;
- does not write to the authoritative LIVE P/L ledger;
- is intended for relative strategy/timing evidence, not margin/slippage simulation.

## Execution invariants — do not weaken

- No LLM may place or size orders.
- No strategy selects leverage directly.
- No reverse-in-one-order shortcut; reversal is CLOSE → confirmed FLAT → OPEN.
- No stale signal may reopen after a hard/risk close; fresh entry evidence is required.
- No pyramiding unless introduced later as a separately reviewed policy.
- No generic arbitrary Saxo OPEN path.
- No unrelated account cash or unrealized profit in pilot compounding.
- No approximate P/L booking when authoritative reconciliation is unavailable.
- No shadow benchmark result in the authoritative LIVE equity ledger.
- CLOSE/reduce safety must not be blocked by entry-budget constraints.

## What is proven vs. what remains to prove

### Proven at this checkpoint

- production services are deployed and live;
- canonical/dynamic product identity works for subscribed/discovered Saxo products;
- Technical Core and MACD runtime are producing without observed failures;
- strategy runtime, CLOSE bridge, OPEN gate, risk epoch, P/L reconciliation and compounding are implemented with explicit persistence/idempotency boundaries;
- Manage-only survives later manual re-entry/resize/reversal;
- shadow comparison is isolated/read-only;
- full repository CI is green;
- stream/worker log severity mapping and observer-warning throttling are production-verified after the checkpoint.

### Still empirical / deliberately not claimed

- meaningful live trading edge from any MACD strategy;
- statistically mature forecast calibration;
- real-money robustness of the complete autonomous OPEN→CLOSE→P/L→re-entry loop over many trades and failure modes;
- safe Product Admission for every Saxo product/direction;
- value-add from every context/AI/cross-market layer.

The next trading step should therefore be **observation and a deliberately tiny bounded live pilot**, not a broad increase in execution scope.

## Known non-blocking technical debt

1. **Legacy naming:** several hardened compatibility adapters retain `_v1` names although they participate in the v2 architecture. Do not rename casually.
2. **Railway CI coupling:** service source config currently reports `checkSuites=false`; CI-before-merge is enforced procedurally rather than by Railway deploy gating.
3. **Historical docs:** older handoffs describe earlier migration stages. This file is current status authority.

Resolved after the stable checkpoint:

- **Logging severity mapping:** fixed and production-verified by `#240` + explicit Railway application in `#241`.
- **Observer RiskControl warning noise:** duplicate non-executable `eligible=False` warnings are throttled without changing persisted risk state or execution eligibility.

None of the remaining items justify broad refactoring before the baseline has been observed in normal operation.

## Stable development rule from here

```text
fresh main
→ one bounded capability
→ focused tests
→ full compile + pytest
→ self-review / architecture review
→ fresh-main check
→ expected-head merge
→ verify exact Railway deployment SHA
→ inspect runtime, not only deployment status
```

For execution-sensitive work, production success means both CI success **and** post-deploy runtime evidence.

## Recommended freeze point

Treat `#239` as the **2026-08-30 architectural stable checkpoint**, with `#240`/`#241` as verified observability-only cleanup layered on top. Observe production before starting another architectural expansion. When development resumes, use this document plus fresh `main` as the handoff baseline.