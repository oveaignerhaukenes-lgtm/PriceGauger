# PriceGauger DB v2 foundation

## Purpose

DB v2 is the storage contract for the PriceGauger v2 architecture. It is intentionally simpler than the accumulated v1 schema and is not required to preserve backward compatibility with v1 PostgreSQL tables.

The design goal is to persist durable market facts, explicit hypotheses, recipes, decisions and outcomes without mirroring every Python object or runtime intermediate.

## Design rules

1. Canonical market data is compact and provider-agnostic.
2. Instruments are data, never schema.
3. Provider identifiers are stored once in reference mappings, not repeated on every bar.
4. Futures contract lineage remains auditable.
5. Technical state is deterministic and recipe-versioned.
6. Forecasts, theses and decisions are immutable historical claims.
7. Context updates are sparse and linked to a stable thesis while its foundation remains valid.
8. Layer outputs are independently identifiable so recipes can be ablated and compared.
9. Operational state is latest-only unless historical runtime state has demonstrated analytical value.
10. Intermediate calculations are not persisted merely because they exist in code.

## Core entities

### markets

Represents the economic market or analysis target: Gold, Silver, Brent, DXY, an equity, an FX pair, and so on.

Suggested fields:

- `market_id` BIGINT primary key
- `name` TEXT
- `category` TEXT
- `base_currency` TEXT nullable
- `quote_currency` TEXT nullable
- `canonical_unit` TEXT nullable
- `active` BOOLEAN
- `created_at` TIMESTAMPTZ

The market identity is stable across provider contract rollovers.

### instruments

Represents a concrete tradable/feed instrument. A futures contract is one instrument; the next contract is another instrument even when both belong to the same market.

Suggested fields:

- `instrument_id` BIGINT primary key
- `market_id` BIGINT references markets
- `instrument_type` TEXT
- `display_name` TEXT
- `valid_from` TIMESTAMPTZ nullable
- `valid_to` TIMESTAMPTZ nullable
- `active` BOOLEAN
- `created_at` TIMESTAMPTZ

### instrument_sources

Maps an internal instrument to provider identity and metadata.

Suggested fields:

- `instrument_source_id` BIGINT primary key
- `instrument_id` BIGINT references instruments
- `provider` TEXT
- `provider_instrument_id` TEXT
- `asset_type` TEXT nullable
- `symbol` TEXT nullable
- `price_multiplier` NUMERIC nullable
- `metadata_json` JSONB nullable for provider-specific fields that are genuinely sparse
- `valid_from` TIMESTAMPTZ nullable
- `valid_to` TIMESTAMPTZ nullable
- `active` BOOLEAN

Unique provider identity should be enforced across `(provider, provider_instrument_id, valid_from)` or the closest stable equivalent.

### collection_subscriptions

Controls which instruments are actively collected. The Saxo catalogue may expose thousands of instruments; PriceGauger should only persist bars for enabled subscriptions.

Suggested fields:

- `instrument_id` BIGINT primary key
- `enabled` BOOLEAN
- `resolution` TEXT default `1m`
- `enabled_at` TIMESTAMPTZ
- `disabled_at` TIMESTAMPTZ nullable

### market_bars_1m

Canonical compact one-minute OHLC.

Suggested fields:

- `instrument_id` BIGINT references instruments
- `bar_time` TIMESTAMPTZ
- `open` DOUBLE PRECISION
- `high` DOUBLE PRECISION
- `low` DOUBLE PRECISION
- `close` DOUBLE PRECISION
- optional `volume` DOUBLE PRECISION nullable
- optional `quality_flags` INTEGER nullable

Primary key: `(instrument_id, bar_time)`.

No provider metadata or repeated JSON payload belongs in this table.

### technical_recipes

Versioned deterministic technical configuration.

Suggested fields:

- `technical_recipe_id` UUID primary key
- `name` TEXT
- `version` INTEGER
- `parameters_json` JSONB
- `created_at` TIMESTAMPTZ
- immutable after creation

### technical_states

Persist only technical state required for audit, reconstruction or fast downstream use. The exact cadence is intentionally not fixed by DB v2 foundation; Technical Core may choose every-bar, change-driven, or checkpointed persistence so long as semantics remain explicit.

Suggested fields:

- `technical_state_id` UUID primary key
- `market_id` BIGINT references markets
- `as_of` TIMESTAMPTZ
- `technical_recipe_id` UUID references technical_recipes
- typed commonly queried features such as regime/trend/momentum/volatility where stable
- `features_json` JSONB for versioned secondary features that do not justify schema churn
- `created_at` TIMESTAMPTZ

Uniqueness should prevent duplicate state production for the same market/as-of/recipe.

### analysis_recipes

Identifies exactly which analysis layers are enabled and which versions produced a composed forecast.

Suggested fields:

- `analysis_recipe_id` UUID primary key
- `name` TEXT
- `version` INTEGER
- `technical_recipe_id` UUID
- `enabled_layers_json` JSONB
- `layer_versions_json` JSONB
- `created_at` TIMESTAMPTZ

Examples include `TA`, `TA+CrossMarket`, `TA+CrossMarket+Regime`, `TA+Macro`.

### forecasts

Immutable forecast claim.

Suggested fields:

- `forecast_id` UUID primary key
- `market_id` BIGINT
- `as_of` TIMESTAMPTZ
- `horizon_seconds` INTEGER
- `technical_state_id` UUID
- `analysis_recipe_id` UUID
- terminal prediction fields
- baseline/composed uncertainty fields
- compact structured path specification where required for faithful rendering
- `created_at` TIMESTAMPTZ

A forecast must never be rewritten after publication. A changed recipe or changed input state creates a new forecast identity.

### forecast_layer_outputs

Stores cacheable structured outputs from optional refinement layers. This is what enables fast UI recomposition without rereading the DB or rerunning expensive analysis.

Suggested fields:

- `layer_output_id` UUID primary key
- `market_id` BIGINT
- `as_of` TIMESTAMPTZ
- `layer_name` TEXT
- `layer_version` TEXT
- `input_fingerprint` TEXT
- structured modifiers: directional bias, velocity/timing, uncertainty, reversal risk, squeeze risk, setup constraints, regime confidence as applicable
- `details_json` JSONB for layer-specific bounded detail
- `created_at` TIMESTAMPTZ

Layer outputs are facts about what a layer concluded from a specific input snapshot; UI selection must not mutate them.

### forecast_outcomes

Objective realized result for a forecast horizon, derived from canonical price data.

Suggested fields:

- `forecast_id` UUID primary key references forecasts
- `matured_at` TIMESTAMPTZ
- realized terminal price / return fields
- error metrics
- status TEXT
- `recorded_at` TIMESTAMPTZ

### context_theses

Immutable full semantic thesis created only when the external/context foundation materially changes.

Suggested fields:

- `context_thesis_id` UUID primary key
- `market_id` BIGINT nullable when thesis spans markets
- `as_of` TIMESTAMPTZ
- `thesis_type` TEXT
- `claim` TEXT
- `directional_or_risk_implication` TEXT
- `evidence_summary` TEXT
- `strengtheners` TEXT nullable
- `invalidators` TEXT nullable
- `missing_information` TEXT nullable
- `structured_claim_json` JSONB nullable
- `created_at` TIMESTAMPTZ

### context_thesis_updates

Short append-only follow-ups while the same thesis remains valid.

Suggested fields:

- `context_update_id` UUID primary key
- `context_thesis_id` UUID references context_theses
- `as_of` TIMESTAMPTZ
- `update_type` TEXT
- `summary` TEXT
- `structured_update_json` JSONB nullable
- `created_at` TIMESTAMPTZ

### raw_evidence

Stores source material needed for audit/re-analysis without copying the same full text into multiple downstream snapshots.

Suggested fields:

- `evidence_id` UUID primary key
- `source_type` TEXT
- `source_id` TEXT
- `published_at` TIMESTAMPTZ nullable
- `observed_at` TIMESTAMPTZ
- `content_text` TEXT nullable
- `content_hash` TEXT
- `metadata_json` JSONB nullable

Theses/updates should reference evidence rather than duplicate it.

### ai_decisions

Structured AI proposal/management decision. AI remains a consumer above Technical Core and enabled context channels.

Suggested fields:

- `ai_decision_id` UUID primary key
- `market_id` BIGINT nullable
- `as_of` TIMESTAMPTZ
- `analysis_recipe_id` UUID
- optional `forecast_id`
- action enum such as HOLD / ENTER / REDUCE / EXIT / MODIFY_RISK
- direction nullable
- confidence nullable
- technical_basis TEXT
- context_effect TEXT nullable
- invalidation TEXT nullable
- structured_decision_json JSONB
- `human_summary` TEXT
- `created_at` TIMESTAMPTZ

The structured record is authoritative for machine evaluation; `human_summary` is the concise frontend companion.

### strategy_recipes and risk_policies

Foundation storage for configurable trading experiments. These tables do not themselves authorize execution.

A strategy recipe may reference an analysis recipe plus explicit entry/exit/management rules. A risk policy should support at minimum maximum per-trade exposure, maximum per-instrument exposure, maximum total exposure, stop-loss/take-profit constraints, session loss limits, allowed instruments, and SIM/LIVE policy.

Advanced trailing, scale-out and dynamic de-risking rules should be versioned strategy capabilities rather than implicit DB behavior.

### runtime_status

Latest operational state only.

Suggested key/value or typed step status keyed by service/stage with `updated_at`. Do not create an append-only heartbeat history unless a concrete diagnostic requirement justifies it.

## Dynamic Saxo onboarding flow

The expected user flow is:

`Saxo catalogue -> select instrument -> resolve/create market -> create instrument -> store Saxo mapping -> enable collection subscription -> accumulate canonical bars -> Technical Core becomes eligible when enough history exists`

Selecting a new Saxo instrument must not require a schema migration or hard-coded market list.

`config/saxo_instruments.json` may remain temporarily as bootstrap/fallback for v1-era test instruments, but DB v2 should become the authoritative dynamic instrument registry.

## Futures rollover

Rollover must preserve both economic continuity and concrete contract identity.

Example:

`Gold market -> Gold Oct 2026 instrument -> Gold Dec 2026 instrument -> ...`

Historical bars remain attached to the exact instrument that produced them. A later continuous-market view may stitch or normalize contracts explicitly, but raw contract identity is never erased.

## Migration stance

The legacy v1 PostgreSQL schema may remain read-only for reference. DB v2 should start clean unless a legacy dataset is demonstrably useful and cheap to migrate.

Canonical one-minute price history is the strongest migration candidate if it can be transformed safely into the compact v2 format. Repetitive JSON state snapshots are not migration requirements.

## Out of scope for this foundation

- switching production runtime from v1 stores to DB v2;
- choosing exact Technical State persistence cadence;
- defining every indicator in Technical Core;
- implementing AI execution autonomy;
- choosing final AutoTrader trailing/scale-out policies;
- physically migrating or deleting the current production database.

Those are separate bounded capabilities after this contract is reviewed and merged.
