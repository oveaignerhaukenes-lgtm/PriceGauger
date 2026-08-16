# Parallel forecast evaluation v2

AP7 establishes a controlled benchmark between the deterministic Technical baseline and the first Technical + Context composition.

For one market, forecast timestamp and horizon, both candidates share the same stable `outcome_key`. This prevents later evaluation from comparing forecasts against different targets.

## Candidates

- `TECH_ONLY` is the unchanged `TechnicalBaselineForecast` control group.
- `TECH_CONTEXT` is the `HolisticForecastV1` treatment generated from that same technical baseline plus one canonical ContextSnapshotV2.

The experiment identity includes both candidate fingerprints and Context provenance. A changed Context state creates a new experiment but does not change the outcome target for the same market/as-of/horizon.

## Persistence

`pg_v2_forecast_experiments` stores the immutable paired forecast payload before the outcome is resolved. Duplicate experiment identity is idempotent.

Outcome resolution is intentionally deferred to a separate bounded capability. AP7 does not read future market data, score performance, learn weights, change production UI, retire legacy paths or affect execution.
