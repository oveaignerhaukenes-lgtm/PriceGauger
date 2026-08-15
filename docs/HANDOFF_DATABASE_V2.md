# Handoff — Database v2

## Mission

Own PriceGauger's persistent contract and keep the v2 architecture generic, auditable, and restart-safe. The database thread is responsible for schema evolution, persistence helpers, migrations, integrity constraints, query ergonomics, and data-health diagnostics — not for deciding market direction.

## Current architectural contract

The v2 database must support this chain:

```text
market/provider instrument identity
→ canonical market observations
→ Technical Core states
→ immutable technical/analysis recipes
→ cached layer outputs
→ forecasts
→ realized outcomes/evaluation
→ runtime health
```

Important existing modules/documents include `db_v2_schema.sql`, `db_workspace_persistence_v2.py`, `instrument_registry_v2.py`, `workspace_loader_v2.py`, `recipe_registry_v2.py`, `runtime_health_v2.py`, and `docs/DB_V2_FOUNDATION.md`.

## Non-negotiable invariants

- PostgreSQL is the real backend; SQLite may remain useful for isolated/local tests but must not define production semantics.
- New Saxo/provider instruments must be registrable without schema or Technical Core code changes.
- Provider identity must be preserved explicitly; do not collapse provider IDs into display symbols.
- Forecasts, states, layer outputs, recipes, and outcomes must retain enough provenance to reconstruct exactly what was known and what recipe produced a result.
- Recipe definitions are immutable. A semantic change requires a new version.
- Same semantic runtime input must not create unbounded duplicate records.
- DB constraints should enforce important semantic uniqueness where practical; do not rely only on application discipline.
- Historical rows should not silently change meaning after code updates.
- UI reads must be read-only unless the feature explicitly owns a write path.

## Dynamic instruments

The instrument registry is intended to expand as the user selects instruments from Saxo. The DB layer should therefore own generic relationships such as:

```text
Market
  ↕
Instrument
  ↕
Provider identity (provider + provider_instrument_id)
  ↕
Subscription / canonical data stream
```

Do not add per-market columns or hard-coded instrument tables for gold, silver, oil, etc.

## Forecast and layer persistence

TA-only is the control forecast family. Optional refinement layers are cached/persisted separately and composed through explicit analysis recipes. Database work must preserve that separation.

A layer output should be attributable to the workspace/input fingerprint and its exact layer version. A composed forecast must remain attributable to the Technical State and recipe that generated it.

## Outcome/evaluation

Outcome data is part of the primary learning loop. Preserve realized values and evaluation metrics rather than overwriting forecasts after the fact. Evaluation should remain append/reconstructable and tied to explicit forecast identities.

## Runtime health

Persist enough status to distinguish healthy, stale, degraded, and missing runtime stages. Avoid conflating data freshness with model confidence.

## Working protocol

Start every change from fresh `main`. One bounded capability per branch/PR. Add focused tests for schema and persistence semantics. Prefer migrations/additive compatibility over destructive rewrites. Never change forecast meaning merely to make a migration convenient.

## Immediate next priorities

1. Validate v2 schema on the real PostgreSQL deployment and ensure all tables/constraints are actually applied.
2. Verify dynamic Saxo instrument registration/subscription against real selected instruments.
3. Exercise state → baseline → layer cache → forecast → outcome persistence end to end.
4. Add operational diagnostics for DB growth, duplicate pressure, stale rows, failed writes, and migration/version state.
5. Coordinate with visualization and TradingDesk threads on read models rather than exposing raw schema assumptions in UI code.

## Out of scope

Do not decide technical weighting, generate forecasts, implement trading strategy, or send Saxo orders. The database supports those systems; it does not own them.
