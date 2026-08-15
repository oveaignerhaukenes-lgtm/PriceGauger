# PriceGauger v2 — System Overview

## Purpose

PriceGauger v2 is a layered market-analysis and trading-support architecture with a deterministic technical baseline at the bottom, explicit optional refinement layers above it, a measurable forecast/outcome loop, and separate human/execution surfaces on top.

The core design goal is not one opaque model that "understands the market." Each contribution should be inspectable, switchable, versioned, testable, and measurable.

## End-to-end flow

```text
Provider / Saxo instrument data
        ↓
Dynamic instrument registry
        ↓
Canonical 1m observations
        ↓
Canonical resampling
1m → 5m / 15m / 30m / 1h / 4h
        ↓
Deterministic Technical Core
        ↓
TechnicalCoreState
        ↓
Technical baseline forecasts
        ↓
Workspace snapshot
        ↓
Optional cached refinement layers
        ↓
Recipe-composed forecast
        ↓
Visualization / TradingDesk / AI decision consumer
        ↓
AutoTrader execution and risk controls
        ↓
Observed market outcome
        ↓
Forecast evaluation and calibration
```

## Deterministic baseline

Canonical 1m data is normalized to UTC and resampled through one shared timeframe contract. Missing minutes remain gaps; no synthetic forward-fill is introduced. Live analysis may include the currently forming bucket using the latest real observation.

Technical Core is deliberately context-blind. It consumes technical snapshots and produces a versioned `TechnicalCoreState` containing trend, momentum, volatility, structure, score, confidence, and timeframe snapshots.

The state is converted into technical baseline forecasts with explicit horizons, expected return, uncertainty bounds, direction, confidence, and path shape. This TA-only layer is the permanent fallback and the empirical control group.

## Workspace and refinement layers

A `WorkspaceSnapshotV2` holds one coherent market/as-of Technical Core state, its technical baselines, and optional cached layer outputs. Higher layers do not rebuild the market from raw data. They return bounded modifiers that can be composed onto the baseline.

Conceptually:

```text
TA-only
  + Technical Interpreter
  + CrossMarket
  + Regime
  + Macro / News
  + future bounded layers
```

This permits rapid layer switching after computation and lets the user see exactly what changed the forecast.

The first bounded AI layer is Technical Interpreter. It sees technical information only and produces structured probabilities/modifiers plus a short human-readable summary. It cannot silently replace Technical Core.

## Recipes and evaluation

Each forecast configuration has an explicit immutable recipe identity, for example `TA-only v1` and `TA+Interpreter v1`. Future combinations must receive new explicit recipe identities with pinned layer versions.

Forecasts are falsifiable. When a horizon matures in active market time, outcome evaluation can record realized return, signed/absolute error, direction hit, and interval coverage.

```text
forecast → market outcome → evaluation → calibration
```

This is how PriceGauger should determine whether a refinement layer adds real edge.

## Runtime properties

The v2 runtime is designed for restart safety and semantic idempotency. Reprocessing the same semantic input converges on the same state/forecast identity rather than creating random duplicates. Runtime health is explicit: `HEALTHY`, `STALE`, `DEGRADED`, or `NO_DATA`.

## Frontend and visualization

The frontend consumes persisted analysis; it is not the source of truth. The first v2 surface is intentionally read-only so the baseline can be inspected without cutting over the existing production analysis path.

The visualization target is interactive layer inspection: stable TA geometry, optional layer refinements, uncertainty, path shape, outcome/error information, and an explicit indication of which recipe/layers are visible.

## TradingDesk

TradingDesk is the human cockpit. It should present charts, indicators, forecasts, context, selected layers, instrument/product information, and explicit manual buy/sell controls. It must not bypass AutoTrader. Execution requests go through the AutoTrader validation/precheck/confirmation path.

## AutoTrader

AutoTrader is a separate execution and risk-control subsystem. It owns validation, sizing, Saxo precheck, confirmation, risk limits, order submission, execution state, exits, and later controlled automation.

The first trading capability remains user-initiated manual execution. Automated strategies should be introduced only after manual execution/risk handling is stable and tested, preferably in SIM and with tightly bounded capital/risk.

Later, an AI decision companion may consume selected PriceGauger information channels and propose actions, but it must operate through structured decision records and AutoTrader guardrails.

## Database

The database is the system memory and contract boundary. It must preserve dynamic instrument identity, canonical observations, technical states, recipes, layer outputs, forecasts, outcomes, runtime status, and relevant trading state without collapsing subsystem boundaries.

New instruments and new analysis layers should be representable generically rather than requiring market-specific schema changes.

## Operating principle

```text
data
→ deterministic baseline
→ optional explicit refinements
→ measurable forecast
→ human/AI decision
→ risk-controlled execution
→ observed outcome
→ learning
```

At any time, higher layers must be removable so the system can return to the deterministic technical baseline. That decomposability is the main safeguard against black-box behavior and the basis for meaningful calibration.
