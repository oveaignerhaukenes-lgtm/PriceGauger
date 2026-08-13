# PriceGauger v2 architecture foundation

## Version boundary

PriceGauger v1 is frozen at commit `443e144275407670230397f36aa6a9ea1bc56ba2` and preserved on branch `archive/v1-final`.

All architectural development after that point belongs to PriceGauger v2. v2 is intentionally allowed to replace v1 storage and analysis contracts. Backward compatibility with the v1 database is not a design requirement.

`main` remains the single integration branch. New v2 work still follows fresh-main -> isolated branch -> bounded capability -> tests -> CI -> review -> fresh-main check -> merge.

## Core principle

PriceGauger v2 starts from the simplest deterministic market model and earns additional complexity layer by layer.

The default analysis path is:

`canonical market data -> deterministic Technical Core -> baseline forecast -> outcome`

Everything else is an optional refinement layer that must remain inspectable, removable and measurable.

A layer is not allowed to remain influential merely because its explanation is plausible. It must improve outcomes or provide a clearly useful constraint/diagnostic role.

## Layer 0 — canonical market data

The canonical dataset is compact market history. One-minute OHLC is the default retained resolution for enabled instruments.

Market data storage must be provider-agnostic. Saxo identifiers and metadata belong in reference/mapping tables, not repeated in every bar.

The system must support dynamically adding instruments selected from the Saxo catalogue without schema changes or instrument-specific code paths.

Conceptually:

`market/instrument registry -> provider mapping -> collection subscription -> compact 1m bars`

Futures require lineage: an economic market such as Gold may be represented by different tradable contracts over time. Contract identity must remain auditable without making each bar self-describing JSON.

## Layer 1 — deterministic Technical Core

Technical Core is the continuous baseline market model.

Its job is to describe what the market itself is doing without requiring an explanation of why:

- trend and market structure;
- momentum;
- volatility;
- moving-average / VWAP relationships;
- breakout, rejection and mean-reversion state;
- other explicitly versioned technical features used by a recipe.

Same canonical data plus same recipe version must produce the same Technical State and same baseline forecast.

Technical-only forecasts do not require a semantic world thesis. Their claim is conditional:

> Given the current technical structure, what path is justified if the surrounding context does not materially change?

The simplest technically justified path is preferred. Forecast specificity must be earned by evidence rather than decorative shape modelling.

## Forecast composition

The Technical Core produces:

`baseline path + terminal prediction + baseline uncertainty`

Higher layers do not redraw the market from scratch. They may return bounded, structured modifiers such as:

- directional bias;
- velocity / timing adjustment;
- uncertainty adjustment;
- reversal risk;
- squeeze risk;
- allowed/blocked setup classes;
- regime confidence.

The forecast composer applies selected modifiers to the frozen technical baseline.

Historical price data and Technical State are never modified by context layers.

## Layer 2 — simple cross-market priors

The first optional refinement layer contains common, explicit market relationships, for example relationships among DXY, precious metals, yields, energy and broad risk assets.

These relationships are priors, not laws. They are deliberately the "dumb" / most common interpretation and must be versioned and visible.

They may support, oppose or reduce confidence in the technical baseline, but must not silently become a new opaque forecast engine.

## Layer 3 — regime-aware relationships

Regime analysis determines which transmission relationships are likely to be active now.

The same market move may have different implications under different marginal-pricing regimes. Regime therefore interprets or gates simple cross-market priors rather than replacing the Technical Core.

Ideas developed in v1 — CrossMarketState, ResponseDivergence and TransmissionState — remain useful candidate tools for this layer, but v2 does not assume that their existing v1 storage or weighting contracts should be retained.

## Layer 4 — external semantic context

Telegram, news, scheduled macro, supply/inventory information and other world-state inputs belong here.

When external context materially changes the interpretation of the market, the system may create an immutable Context Thesis containing at minimum:

- thesis / regime claim;
- directional or risk implication;
- evidence;
- what strengthens it;
- what weakens or invalidates it;
- missing inputs / uncertainty.

While the same foundation remains valid, short thesis updates point back to the existing thesis. A new full thesis is created only when the underlying foundation materially changes.

Conceptually:

`Thesis A -> update -> update -> invalidated -> Thesis B`

This avoids producing large repetitive semantic snapshots on every runtime cycle.

## AI role

AI is a consumer/orchestrator above the deterministic core, not a hidden dependency inside it.

AI may:

- interpret enabled technical and context channels;
- review a forecast or position;
- help a user configure an explicit strategy/analysis recipe;
- summarize reports and external information;
- produce structured decision proposals and position-management suggestions;
- act as a longer-horizon investment companion.

Every AI decision should have both:

1. a structured backend representation suitable for audit/evaluation; and
2. a short human-readable explanation suitable for the UI.

The structured record is authoritative for machine evaluation. The human explanation is a concise companion, not an unbounded hidden reasoning log.

AI must only receive the information channels enabled by the active recipe/session so that layer ablation remains possible.

## Load once, analyse once, recompose quickly

Interactive forecast toggles must not trigger full database reloads, repeated Technical Core calculations or repeated LLM calls when the underlying snapshot has not changed.

The target flow is:

`DB -> loaded workspace snapshot -> technical baseline -> cached layer outputs -> selected composition -> render`

Expensive analysis happens once per relevant data/context version. UI toggles then recombine already computed layer outputs and redraw quickly.

This makes it possible to cycle interactively among:

- Technical only;
- Technical + cross-market;
- Technical + regime;
- Technical + external context;
- other explicitly enabled recipes.

The UI should make the active recipe visible at all times.

## Evaluation / ablation

TA-only is the control group.

Additional layers are introduced and evaluated separately. Each forecast/trading evaluation must identify the exact recipe/layers that were active.

Examples:

`TA`

`TA + simple cross-market`

`TA + regime-aware cross-market`

`TA + regime + macro`

Performance and forecast quality can therefore be compared without conflating multiple architectural changes.

## Execution boundary

The v2 analysis architecture is intentionally separable from execution.

AutoTrader may consume Technical Core and optional context/AI outputs, but execution remains subject to its own explicit risk/policy gate. Analysis layers must not bypass execution constraints.

Initial automated experiments should remain deliberately simple and measurable. More complex management rules are separate strategy capabilities rather than hidden infrastructure behaviour.

## Database design implications

DB v2 should be designed around information semantics rather than mirroring Python object graphs.

Primary classes of persisted information are expected to be:

- market/instrument registry and provider mappings;
- compact canonical market bars;
- versioned Technical States or reproducible technical recipes;
- analysis / forecast recipes;
- immutable forecasts and outcomes;
- sparse Context Theses and thesis updates;
- raw evidence where needed for audit/re-analysis;
- structured AI decisions plus concise human summaries;
- strategy/risk configuration and execution records when that subsystem is addressed;
- latest-only operational/runtime status unless historical status has demonstrated analytical value.

Intermediate calculations should not be persisted merely because they exist in code.

The v1 database may be retained read-only as an archive, but v2 may start with a fresh PostgreSQL schema. Only legacy data that is easy to migrate and demonstrably useful needs to be carried forward.

## Product/UI implication

Overview should expose a concise technical interpretation next to the forecast and show exactly which analysis layers are enabled.

The market page may expose the detailed Technical State, Context Thesis, layer outputs and alternative forecast compositions.

The user should always be able to strip the system back to the deterministic Technical-only baseline and see what each additional layer changes.

## Guiding rule

**Start with the simplest technically justified model. Add information one layer at a time. Preserve the baseline. Measure whether each added layer improves the result.**
