# PriceGauger handoff

## Stable baseline — 13 Aug 2026

This document describes the current architecture on `main`. Treat old feature branches and superseded draft PRs as historical only; new work must always start from fresh `main`.

PriceGauger is currently a live paper-analysis system with a deliberately separated execution subsystem. PostgreSQL is authoritative shared state, Railway runs the web/worker/stream services, and GitHub `main` is the deployment source.

## Authoritative analysis path

The main directional analysis chain is:

`Telegram -> semantic filter / event clusters -> Information State -> Technical State -> Decision State -> multi-horizon Forecast -> Outcome -> ForecastErrorObservation`

Important supporting layers:

- News Context adds regime/context fields but must not add a duplicate directional news impulse.
- Historical Engine can contribute only when an event-scoped historical signal already exists for the Decision State's contributing events. It is a conservative confirmation component, not an independent always-on directional engine.
- The old automatic Historical Runtime producer branch was never integrated and is now considered stale. Historical Engine should therefore be treated as a safe optional/dormant consumer unless a fresh bounded producer capability is deliberately rebuilt from current `main`.
- Decision State stores the actual engine component scores/weights used for auditability.
- Forecasts are immutable. Historical Decision States/forecasts are never rewritten by newer information or learning.

## Cross-market / adaptation observation chain

The cross-market chain is now live and persisted:

`CrossMarketState -> ResponseDivergence -> TransmissionState`

### CrossMarketState

- Produced during each authoritative state-runtime cycle, before the `no_material_change` early return.
- Uses canonical Silver, Gold, Brent and DXY history.
- Tracks 15m / 1h / 4h returns with explicit temporal window coverage.
- Separates latest-observation freshness from horizon reference validity.
- Defines US 2Y / 10Y / 30Y as yield observations, but leaves them explicitly `MISSING` until a verified yield feed exists. Treasury futures prices must never be substituted for yields.
- Persists immutable timestamped snapshots with auditable reference timestamps/offsets.

### ResponseDivergence

- Compares an Information State impulse with a later temporally valid Silver response.
- A response horizon is never allowed to mature early; the full requested horizon must have elapsed after the Information State timestamp.
- Classifies only `ALIGNED`, `DIVERGENT` or `UNCONFIRMED`.
- Gold / Brent / DXY / yields remain descriptive supporting context and are not treated as causal proof.

### TransmissionState

- Interprets mature response observations only as mechanisms consistent with observed evidence.
- Mechanisms: `SAFE_HAVEN`, `RATES_FX`, `ENERGY_INFLATION`, `INDUSTRIAL_GROWTH`, `RISK_LIQUIDITY`.
- Uses discrete evidence classes (`SUPPORTED`, `PARTIAL`, `CONFLICTING`, `INSUFFICIENT`) rather than hand-written channel scores/confidence weights.
- `dominant_channel` is set only when exactly one mechanism is supported and consistent with the realized Silver response; otherwise the state remains `UNRESOLVED`.
- TransmissionState currently has no Decision State, forecast, notification or trading effect.

## Forecast system

Forecast production is multi-horizon and immutable. Current target horizons are:

`5m / 15m / 30m / 1h / 4h / 12h / 24h / 7d`

Each Decision State can persist one deterministic forecast identity per horizon. The historical 4h identity recipe remains backward-compatible.

### What learns today

- Movement magnitude learns from COMPLETE outcomes independently per `market × horizon`.
- Learning is versioned through immutable training recipes.
- Direction learning is still disabled.
- Regime learning is still disabled.
- The established-technical conflict rule remains a deterministic prior for new Decision States; it is not learned direction weighting.

### Forecast path semantics

The terminal expected-move interval remains authoritative.

For the newest active forecast only, the displayed intrahorizon path may use the frozen forecast judgement together with current technical regime and volatility to determine *when* movement is expressed. An opposing technical regime can therefore show an initial counter-move before convergence to an unchanged endpoint; aligned technical state may front-load the move. No random market noise is invented.

Intrahorizon uncertainty is volatility-derived and vanishes at both forecast origin and terminal endpoint, so it never changes the persisted terminal prediction.

Historical forecast geometry is visual context only because path evidence is not persisted. It must not be retrospectively treated as an authoritative minute-by-minute forecast. Forecast accuracy remains terminal/outcome based through the separate immutable error-observation path.

### Forecast chart / diagnostics

- Wall-clock `NOW` is the actual history/forecast boundary when it lies inside the visible chart.
- Left side is realized canonical history; right side is prospective forecast.
- Old forecast trails remain visible while they overlap the chart's retained forecast-history region and fade as historical context.
- Canonical price gaps are not bridged by invented interpolation.
- A horizon-specific signed forecast-error track shows immutable completed errors and display-only rolling diagnostics.
- ResponseDivergence / TransmissionState may be overlaid as temporal adaptation context, but these associations are descriptive and not causal learning weights.

## Market chat

Markedschat is read-only decision support. For every user turn it rebuilds context from authoritative PostgreSQL state and may carry conversation history only as conversational context.

Current context includes Decision State, Technical State, decision-engine components, News Context, event-scoped Historical signal, market mover, Telegram context, forecasts/outcomes and bounded canonical price history.

Known consistency gap: Markedschat does **not yet** include the newer CrossMarketState / ResponseDivergence / TransmissionState / forecast-error adaptation context in its authoritative prompt. Treat that as a separate future bounded capability rather than silently assuming the chat sees those layers.

Markedschat must never create its own market truth, mutate worker status, or execute trades.

## Production data/runtime

- PostgreSQL is canonical backend. SQLite is test-only where appropriate.
- `pricegauger-web`: Streamlit read/render UI.
- `pricegauger-worker`: continuous Telegram/context/state/forecast/outcome runtime.
- server-side Saxo stream service: canonical realtime market-data producer.
- canonical realtime flow: `Saxo stream -> canonical 1m bars -> PostgreSQL -> TradingDesk / analysis`.
- reconnect/backfill repairs recent canonical gaps; browser/PC is never the authoritative stream producer.
- Saxo instrument metadata is versioned in `config/saxo_instruments.json`; do not reintroduce an environment JSON silo unless an intentional temporary override is explicitly required.

When production behavior is in doubt, verify Railway runtime/logs and persisted PostgreSQL state. GitHub deployment metadata alone is not proof that a running service is healthy.

## AutoTrader / execution boundary

AutoTrader is a separate execution/risk-control subsystem.

Current production-development boundary:

- Saxo **SIM only**.
- User-initiated manual execution only.
- Shared AutoTrader/TradingDesk execution component; no parallel order path.
- Product discovery and directional product sizing are read/preparation layers.
- Execution path is `ManualOrderIntent -> server-side validation -> Saxo precheck -> explicit confirmation -> one SIM submit -> authoritative Saxo order/position read-back`.
- Fail closed on stale intent, invalid SIM account, disclaimers/precheck failure or uncertain duplicate-submit state.
- Browser never talks directly to Saxo.

Repository evidence does not currently record the explicit small end-to-end Saxo SIM order that PR #105 required before operational sign-off. Treat the execution code as CI-validated but **runtime verification pending** until a controlled SIM order confirms precheck -> confirmation -> submit -> read-back in the deployed environment.

The old MACD 30m AutoTrader draft was closed as superseded during stable-baseline cleanup. Automatic strategy/entry remains explicitly deferred. Any future automation must begin from fresh `main` and first have authoritative position reconciliation, persisted processed-event state, restart recovery and duplicate-action protection.

## TradingDesk

TradingDesk shares the canonical Saxo/1m data path and the same execution component as AutoTrader.

- Canonical 1m bars resample to supported chart timeframes.
- Bollinger / MACD / RSI are default indicators.
- EMA20 / EMA50 / SMA50 / Stochastic / ATR are available.
- Page-specific controls live in the right control surface on wide layouts.
- No parallel OAuth, market-data silo or execution motor is permitted.

## Analysis status / degradation

`AnalysisStatusStore` is the user-visible health contract for runtime stages.

- Expected missing/stale data is represented explicitly rather than disguised as a crash.
- Independent observation layers degrade locally where practical.
- CrossMarketState failure causes ResponseDivergence / TransmissionState to be skipped rather than bringing down the main analysis cycle.
- Healthy no-material-change technical reuse is surfaced as `REUSED/Gjenbrukt`, not as a misleading missing-analysis state.

## Architecture discipline

For every new capability:

1. Fresh `main`.
2. Isolated branch.
3. One bounded capability.
4. Focused tests.
5. Full GitHub Actions CI.
6. Draft PR.
7. Architecture/diff review.
8. Fresh-main check.
9. Merge with exact-head guard.
10. For runtime changes, verify production service behavior after deployment.

Do not resume stale branches blindly. Do not change three architectural concepts in one PR. Do not hide heuristics. Version priors/recipes. Preserve traceability:

`forecast -> decision -> component scores/weights -> context -> outcome -> error observation -> learning recipe`

The central learning principle remains:

**Semantics may propose explanations; observed data and outcomes decide which explanations deserve weight.**

PriceGauger must get better at detecting when its model was wrong, not merely at explaining afterward why its original story sounded plausible.

## Intentional gaps / next candidates

These are not regressions; they are explicitly incomplete capabilities:

- verified Treasury 2Y / 10Y / 30Y yield feed;
- scheduled macro state for CPI / PPI / NFP with actual-consensus-revisions plus observed market response;
- empirically validated direction learning and regime/transmission adaptation per market × horizon × regime;
- richer industrial-growth/liquidity proxies for TransmissionState;
- fresh Historical Runtime producer if Historical Engine is to become live rather than optional/dormant;
- Markedschat context upgrade for CrossMarket / ResponseDivergence / Transmission / adaptation diagnostics;
- controlled deployed Saxo SIM end-to-end verification of the manual execution path;
- persistent thesis/follow mode and interactive counterfactual scenario workspace;
- automatic trading only after separate explicit approval and execution-state safety work.

Do not add new signals merely to increase feature count. Prefer production observation, outcome accumulation and identifiable learning improvements.
