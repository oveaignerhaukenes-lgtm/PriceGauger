# PriceGauger v2 — System Overview

## Purpose

PriceGauger v2 is built as a layered market-analysis system with a deterministic technical baseline at the bottom, explicit and optional refinement layers above it, a measurable forecast/outcome loop, and separate human/execution surfaces on top.

The central design goal is not to create one opaque model that "understands the market." The goal is to make each contribution inspectable, switchable, versioned, testable, and measurable.

## End-to-end flow

```text
Provider / Saxo instrument data
        ↓
Dynamic instrument registry
        ↓
Canonical 1m observations
        ↓
Canonical resampling contract
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
Optional cached analysis layers
        ↓
Recipe-composed forecast
        ↓
UI / TradingDesk / AI decision consumer
        ↓
AutoTrader execution and risk controls
        ↓
Observed market outcome
        ↓
Forecast evaluation and calibration
```

## 1. Dynamic instruments and canonical data

The v2 instrument path is data-driven. Instruments are represented by their market relationship and provider identity rather than by hard-coded symbols in the analysis engine. A new Saxo instrument can therefore be registered and subscribed without adding special cases to Technical Core.

Canonical 1m observations are the common market-data input for the technical baseline. Provider-specific identity is preserved so later source, rollover, and instrument-specific behavior can remain explicit.

## 2. Canonical timeframe contract

Technical analysis consumes one shared timeframe contract. Canonical 1m observations are normalized to UTC and resampled into 5m, 15m, 30m, 1h, and 4h buckets.

Important invariants:

- bucket alignment is deterministic;
- missing canonical minutes are not forward-filled;
- gaps remain absence of evidence rather than synthetic flat prices;
- live analysis may include the currently forming bucket using the latest real observation;
- the same input produces the same timeframe geometry.

## 3. Deterministic Technical Core

Technical Core is deliberately context-blind. It does not know about CPI, wars, shortages, news, narratives, or external macro interpretation.

It reads technical snapshots and produces a `TechnicalCoreState`, including trend, momentum, volatility, structure, score, confidence, timeframe snapshots, and a versioned technical recipe identity.

This is the permanent fallback layer: even if every AI/context layer is disabled or unavailable, PriceGauger must still be able to produce the technical baseline.

## 4. Technical baseline forecast

The deterministic state is converted into baseline forecasts for explicit horizons. A baseline contains direction, expected return, lower/upper uncertainty bounds, confidence, path shape, and the exact Technical Core state it was derived from.

The baseline is intentionally simple. Its purpose is to establish a reproducible forecast family that can be falsified, calibrated, and compared against richer layers.

## 5. Workspace and refinement layers

A `WorkspaceSnapshotV2` is the reusable analysis workspace for one market/as-of state. It contains the Technical Core state, technical baseline forecasts, and optional cached layer outputs.

Higher layers do not rebuild the market from raw data. They receive the already-defined workspace/input contract and return bounded modifiers. The composed forecast then adjusts the baseline. This supports very fast layer switching after the layer outputs have been computed.

Conceptually:

```text
TA-only
   + Technical Interpreter
   + CrossMarket
   + Regime
   + Macro / News
   + other future layers
```

Layers are additive refinements, not replacement forecast engines.

## 6. Technical Interpreter

Technical Interpreter is the first bounded AI refinement layer. It sees technical information only. Its role is to apply ordinary technical reasoning across interacting indicators — for example momentum, structure, resistance, rejection/breakout probability, continuation versus mean reversion, and squeeze risk.

It returns validated structured output plus a short human-readable summary. It cannot silently replace Technical Core and it is not required for TA-only operation.

## 7. Recipes and semantic versioning

Every meaningful forecast configuration has an explicit recipe identity. Examples include:

- `TA-only v1`
- `TA+Interpreter v1`

Future combinations must receive their own explicit identities and pinned layer versions.

This makes historical evaluation meaningful: an old forecast cannot change semantic meaning because the implementation later evolved.

## 8. Forecast outcome loop

Forecasts are falsifiable. Once a forecast horizon matures in active market time, PriceGauger can compare the forecast with what actually happened.

The v2 evaluation contract supports metrics such as realized return, signed error, absolute error, direction hit, and interval coverage.

This closes the empirical loop:

```text
forecast → market outcome → evaluation → calibration
```

The purpose is to determine which layers add real edge rather than merely producing plausible explanations.

## 9. Runtime health and idempotency

The v2 runtime is designed for continuous operation and restart safety. Reprocessing the same semantic input converges on the same Technical State / forecast identities instead of creating random duplicates.

Runtime health is explicit (`HEALTHY`, `STALE`, `DEGRADED`, `NO_DATA`) and persistence includes semantic uniqueness constraints.

## 10. Frontend and visualization

The UI is a consumer of persisted analysis, not the source of truth. The first v2 surface is intentionally read-only so the new baseline can be inspected without cutting over the existing production analysis path.

The visualization target is interactive layer inspection: technical baseline as the stable geometry, optional layer refinements, uncertainty, path shape, outcome/error information, and clear indication of exactly which recipe/layers are being displayed.

## 11. TradingDesk

TradingDesk is the human cockpit. It should make PriceGauger analysis actionable without bypassing execution controls.

It presents charts, indicators, forecasts, context, selected layers, instrument/product information, and manual buy/sell interaction. Execution requests are passed to AutoTrader rather than sent directly to Saxo.

## 12. AutoTrader

AutoTrader is a separate execution and risk-control subsystem. It owns validation, product sizing, precheck, confirmation, risk limits, order submission, execution state, exits, and later controlled automation.

The first user-facing trading capability remains manual and explicit. Automated strategies should be introduced only after the manual execution/risk path is stable and tested, preferably in SIM and under tightly bounded capital/risk constraints.

Later, an AI decision companion can consume selected PriceGauger information channels and propose actions, but it must operate through structured decision records and AutoTrader guardrails.

## 13. Database responsibility

The database is the shared memory and contract boundary across the system. It must preserve instrument identity, canonical observations, technical states, recipes, layer outputs, forecasts, outcomes, runtime status, and relevant trading state without smearing the boundaries between subsystems.

The database should support new instruments and new layers generically rather than requiring per-market schema changes.

## 14. Operating principle

PriceGauger v2 should remain decomposable:

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

At any point, the user should be able to remove higher layers and return to the deterministic technical baseline. That is the core safeguard against an opaque black-box system and the basis for empirical calibration.
