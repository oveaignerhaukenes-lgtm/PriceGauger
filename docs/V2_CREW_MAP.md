# PriceGauger v2 — Crew Map

This is the minimum operating crew for the next phase.

| Thread | Owns | Does not own |
|---|---|---|
| Database v2 | schema, persistence, migrations, instrument registry, provenance, outcomes, runtime DB health | forecast judgment, UI design, order strategy |
| Visualization / Graphs v2 | forecast geometry, layer toggles, uncertainty/outcome visualization, reusable chart components | analysis math, DB schema, order execution |
| TradingDesk v2 | human cockpit, market/product selection, analysis presentation, manual trade intent | Saxo order submission, autonomous strategy, core analysis |
| AutoTrader v2 | validation, sizing, risk policy, precheck, confirmation, order/position lifecycle, later bounded automation | technical/context analysis generation, general UI |

## Shared rules

- Start every capability from fresh `main`.
- One bounded capability per branch/PR.
- Preserve the deterministic TA-only baseline as the control layer.
- Higher analysis layers refine; they do not silently replace the baseline.
- Every forecast configuration must have an explicit recipe/version.
- UI should consume persisted/read-model contracts rather than re-run analysis.
- TradingDesk never bypasses AutoTrader.
- AutoTrader remains SIM-first and fail-closed.
- New instruments must be generic/provider-driven rather than hard-coded into analysis logic.
- Outcome measurement is part of the product: changes should remain empirically comparable.

## Primary references

- `docs/PRICEGAUGER_V2_SYSTEM_OVERVIEW.md`
- `docs/PRICEGAUGER_V2_ARCHITECTURE.md`
- `docs/DB_V2_FOUNDATION.md`
- `docs/TECHNICAL_CORE_V2.md`
- `docs/TECHNICAL_INTERPRETER_V2.md`
- `docs/WORKSPACE_COMPOSER_V2.md`
- `docs/TECHNICAL_BASELINE_STABILITY_V2.md`
- the four `HANDOFF_*_V2.md` documents in this directory
