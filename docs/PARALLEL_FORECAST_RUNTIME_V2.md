# Parallel Forecast Runtime v2

AP9 makes the paired forecast benchmark live without changing Technical Core authority.

For every successfully produced Technical Core runtime state, the runtime loads the latest canonical ContextSnapshotV2 and creates one idempotent paired experiment per technical horizon. Each pair contains `TECH_ONLY` and `TECH_CONTEXT` candidates sharing one `outcome_key`.

The same cycle also scans unresolved paired experiments and evaluates mature ones against the existing canonical `MarketHistoryStore` bridge. Outcome resolution reuses the active-market-time semantics from `forecast_outcome_evaluation_v2`, so session closures and long data gaps do not consume forecast horizon.

## Failure boundary

Benchmark collection is observational. Failure in Context loading, experiment persistence, history resolution, or outcome persistence is logged but must not mark the authoritative Technical Core cycle failed. Technical production and runtime health remain independent.

## Deliberately excluded

No learned weighting, automatic recipe changes, LLM retrospective analysis, user mixing controls, UI, legacy retirement, or AutoTrader authority is introduced here.
