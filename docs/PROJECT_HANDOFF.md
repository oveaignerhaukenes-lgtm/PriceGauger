# PriceGauger handoff

## PriceGauger v2 — active architecture

PriceGauger v1 is frozen at commit `443e144275407670230397f36aa6a9ea1bc56ba2` and preserved on branch `archive/v1-final`.

All architectural development after that point belongs to PriceGauger v2. v2 may replace v1 storage and analysis contracts; backward compatibility with the v1 database is not a design requirement.

The authoritative v2 architecture is documented in `docs/PRICEGAUGER_V2_ARCHITECTURE.md`.

`main` remains the single integration branch. Every capability still follows:

fresh `main` -> isolated branch -> one bounded capability -> focused tests -> full CI -> draft PR -> architecture review -> fresh-main check -> exact-head merge.

Do not resume stale v1 feature branches blindly. Treat them as historical references only.

## v2 core model

The default control-group analysis path is:

`canonical market data -> deterministic Technical Core -> baseline forecast -> outcome`

Technical Core is the continuous baseline market model. It should be deterministic, inspectable and reproducible from canonical data plus a versioned recipe.

Additional analysis is layered above the technical baseline rather than blended invisibly into it:

1. simple explicit cross-market priors;
2. regime-aware interpretation of those relationships;
3. external semantic context such as Telegram/news/macro/supply;
4. optional AI review/orchestration/position management.

Higher layers may refine direction bias, velocity/timing, uncertainty, reversal/squeeze risk or permitted setup classes, but they must not silently replace the technical baseline with an unrelated opaque forecast.

The user must always be able to strip the system back to Technical-only and see what each enabled layer changes.

## Forecast composition and UI

The Technical Core produces the baseline path, terminal prediction and baseline uncertainty.

Layer outputs should be structured and cacheable. Interactive forecast toggles should recompose an already-loaded workspace snapshot rather than reread PostgreSQL, rerun Technical Core or call an LLM again when the underlying data has not changed.

Target flow:

`DB -> workspace snapshot -> technical baseline -> cached layer outputs -> selected composition -> render`

The UI should expose the active analysis recipe explicitly, for example Technical-only versus Technical + CrossMarket + Regime + Macro.

Overview should show a short human-readable technical interpretation next to the chart. Detailed layer/state explanations belong on the market page.

## Context Thesis

Technical-only forecasts do not require a semantic thesis.

A Context Thesis becomes relevant when external/world-state information is allowed to modify the baseline. A full thesis is immutable and should state:

- the regime/context claim;
- directional or risk implication;
- evidence;
- what strengthens it;
- what weakens or invalidates it;
- missing inputs/uncertainty.

Short updates point back to the same thesis while its foundation remains intact. A new full thesis is created only when the underlying foundation materially changes.

`Thesis A -> update -> update -> invalidated -> Thesis B`

## AI role

AI is a consumer/orchestrator above the deterministic core, not a hidden dependency inside it.

AI may consume only the information channels enabled by the current recipe/session. It may analyze technicals, interpret context, summarize reports, help configure strategy recipes, propose position-management changes and act as an investment companion.

Every AI decision should produce both:

- a structured backend record suitable for audit/evaluation; and
- a short human-readable explanation suitable for the frontend.

The structured decision record is authoritative for machine evaluation. The human summary is deliberately concise and should not become an unbounded reasoning archive.

## Dynamic instruments

v2 must not hardcode Silver/Gold/Brent/etc. into the database schema or Technical Core.

The system needs a dynamic market/instrument registry with separate provider mappings. Selecting a new Saxo instrument should create/activate data records, not require a schema or code change.

Canonical bars refer to compact internal IDs. Provider metadata such as Saxo UIC, asset type, symbol and price multiplier belongs in reference/mapping tables and is not repeated in every market-data row.

Futures require lineage so multiple tradable contracts can map to the same economic market while preserving which actual contract sourced each observation.

The current `config/saxo_instruments.json` is therefore a v1 bootstrap/fallback mechanism, not the v2 canonical instrument model.

## Database v2 direction

PostgreSQL remains the intended canonical backend, but v2 may start with a fresh schema. The v1 database may remain read-only as an archive. Only legacy data that is easy to migrate and demonstrably useful needs to be carried forward.

The database should be designed around information semantics rather than mirroring Python object graphs.

Expected primary persisted classes:

- market/instrument registry and provider mappings;
- compact canonical 1m OHLC bars;
- versioned Technical States or enough deterministic recipe information to reproduce them;
- analysis/forecast recipes;
- immutable forecasts and outcomes;
- sparse Context Theses and thesis updates;
- raw evidence where audit/re-analysis requires it;
- structured AI decisions plus concise human summaries;
- strategy/risk configuration and later execution records;
- latest-only operational/runtime status unless historical status proves analytically useful.

Do not persist intermediate calculations merely because they exist in code. Avoid repeated self-describing JSON in high-volume time-series tables.

## Evaluation principle

TA-only is the control group.

Additional layers are introduced separately and must identify exactly which recipe/layers were active for each forecast or trading experiment.

Examples:

`TA`

`TA + simple cross-market`

`TA + regime-aware cross-market`

`TA + regime + macro`

This allows genuine ablation: a layer earns influence by improving forecast/trading outcomes or by supplying a clearly useful safety/diagnostic constraint.

## AutoTrader boundary

AutoTrader remains a separate execution/risk-control subsystem. v2 analysis can feed AutoTrader, but analysis layers cannot bypass execution policy.

The initial v2 direction is deliberately measurable: simple Technical-only strategy recipes may be tested first, then extra analysis channels can be enabled one at a time.

Strategy/session configuration should be explicit and auditable. Core risk concepts include maximum exposure, trade/session loss limits, permitted instruments/actions and stop/target policy. More advanced trailing, scaling and dynamic de-risking should be separate strategy-management capabilities rather than hidden defaults.

AI may later help configure or manage a strategy within explicit policy constraints, but the deterministic/risk boundary remains authoritative.

## v1 reference

The complete v1 architecture and implementation remain available at:

`archive/v1-final` -> `443e144275407670230397f36aa6a9ea1bc56ba2`

Useful v1 ideas such as CrossMarketState, ResponseDivergence and TransmissionState are not discarded. In v2 they become candidate context/regime tools that must be reintroduced deliberately and evaluated against the Technical-only baseline rather than assumed to be permanent core layers.

## Immediate v2 build order

1. Freeze/merge this v2 architecture foundation.
2. Define and build DB v2 with dynamic instrument registry and compact canonical price storage.
3. Build deterministic Technical Core v2 against the new data contract.
4. Build baseline Technical-only forecast composition and UI recipe toggles.
5. Connect simple measurable SIM strategy experiments through the separate AutoTrader risk/execution boundary.
6. Reintroduce cross-market, regime, macro/news and AI layers one bounded capability at a time.
7. Create subsystem-specific handoffs for the new crew only after the common v2 foundation is stable.

## Guiding rule

**Start with the simplest technically justified model. Preserve the baseline. Add information one layer at a time. Measure whether each added layer improves the result.**
