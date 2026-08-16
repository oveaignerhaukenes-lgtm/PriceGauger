# PriceGauger v2 cutover stability gate

## Status

This document freezes the first functional v2 cutover contract after the Overview, TradingDesk, onboarding/runtime and manual-execution migrations.

The active user workflow is now:

`Saxo catalogue -> explicit v2 onboarding -> enabled 1m collection subscription -> existing Saxo realtime ingestion -> canonical market history -> Technical Core v2 -> persisted v2 workspace/forecast -> Overview / TradingDesk -> Analyst Companion -> explicit human manual execution -> AutoTrader SIM safety path`

## Active v2 authority

### Market and instrument identity

`pg_v2_markets`, `pg_v2_instruments`, `pg_v2_instrument_sources` and `pg_v2_collection_subscriptions` are the canonical identity/configuration contract for newly onboarded instruments.

TradingDesk must not infer its selected market from `configured_instruments()`. It must resolve persisted v2 workspace identity and an active subscribed v2 provider source.

### Analysis

Overview market cards and TradingDesk analysis read persisted v2 workspace/forecast state. Missing v2 state is explicit degradation; there is no hidden fallback to legacy forecast geometry or legacy Decision State for the active market-card/TradingDesk analysis surface.

Technical Core remains deterministic. Optional cached layers may refine rendering only through the existing v2 composition contract.

### Companion

Analyst Companion is analysis-only and session-scoped. It consumes the same selected v2 forecast view as TradingDesk. It has no sizing, order, precheck, confirmation or execution authority.

### Collection/runtime

The realtime worker polls enabled v2 collection subscriptions and applies them to the existing Saxo stream generation. This is a bridge into the existing ingestion path, not a second ingestion pipeline.

Legacy configured feed instruments remain a compatibility/bootstrap source during the controlled bar-storage migration, but an explicit v2 subscription for the same market supersedes that configured feed in the runtime set. Ambiguous multiple enabled instruments for one canonical market fail closed until an explicit primary-analysis-instrument contract exists.

### Manual execution

TradingDesk manual execution is bound to the exact selected canonical v2 market/instrument/provider identity. That identity is re-resolved before precheck and again immediately before submit.

The bound v2 feed identity is provenance/authorization context only. It does not replace the separately selected Saxo execution product (for example Mini/KO). Forecast and Companion output cannot authorize an order.

Existing SIM-only, sizing, Saxo precheck, explicit confirmation, duplicate suppression and authoritative read-back safeguards remain authoritative.

## Legacy freeze

Legacy code may remain for rollback, historical compatibility, non-cutover context/news surfaces, or the controlled physical 1m bar-store transition. It must not silently regain authority over:

- Overview market-card analysis/forecast rendering
- TradingDesk market selection or analysis identity
- TradingDesk Companion context
- TradingDesk manual execution provenance
- v2 onboarding subscriptions

Any change that reintroduces a legacy fallback into those active paths requires an explicit architecture decision and a new bounded migration capability.

## Stability gate

A v2 cutover candidate is acceptable only when CI proves the following contracts remain true:

1. Overview active market cards render through the v2 read model.
2. TradingDesk selects markets through the persisted v2 context and does not import `configured_instruments()` as its selection root.
3. TradingDesk renders Companion from the same v2 forecast context.
4. TradingDesk passes an explicit `AutoTraderExecutionContextV2` into the shared manual-execution panel.
5. Manual execution fingerprints and revalidates v2 identity without substituting the selected execution-product UIC.
6. Realtime worker discovers v2 collection subscriptions and feeds the same mutable runtime instrument set to both Saxo streaming and Technical Core v2.
7. Missing, stale, remapped or ambiguous canonical identity fails closed instead of guessing.

The source-level contract test in `tests/test_v2_cutover_stability_gate.py` protects these architectural seams in addition to the existing behavioral tests for each subsystem.

## Deferred, not hidden

The physical canonical bar store is still in controlled transition: the live chart and Technical Core bridge can continue to consume the existing canonical `realtime_bars_1m` / `MarketHistoryStore` adapter while market/instrument authority is v2. Moving bars fully into compact `pg_v2_market_bars_1m` is a separate capability and must not be smuggled into this stability gate.
