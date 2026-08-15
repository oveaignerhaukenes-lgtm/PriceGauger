# Handoff — Visualization / Graphs v2

## Mission

Own the visual language that turns PriceGauger's layered analysis into something a human can inspect, compare, and challenge quickly. The graph thread does not invent market analysis; it visualizes persisted and composed analysis contracts faithfully.

## Core concept

The visual model should mirror v2 architecture:

```text
price history
+ deterministic TA baseline forecast
+ uncertainty
+ optional refinement layers
+ outcome/error feedback
```

The baseline geometry is primary. Higher layers refine that geometry rather than replacing it with unrelated curves.

## Primary user interaction

The user should be able to switch analysis layers on/off and understand exactly what forecast is being viewed. After layer outputs have been computed, switching should be close to instantaneous because the UI composes cached outputs rather than re-running raw data analysis.

Target controls conceptually resemble:

```text
[x] Technicals
[x] Technical Interpreter
[ ] CrossMarket
[ ] Regime
[ ] Macro / News
```

The visible recipe/layer identity must always be clear.

## What the graph should communicate

- observed price history and current point;
- expected path, not merely an arrow or bullish/bearish score;
- uncertainty/fan or interval around the path;
- different horizons without confusing scale;
- whether the path implies drift, pullback, squeeze, mean reversion, rejection, breakout, etc., when the analysis contract supports it;
- what changed when a refinement layer is enabled;
- runtime/data health when a forecast is stale or degraded;
- realized forecast error/outcome where useful.

The graph's first job is to show the forecasted development. Named chart patterns or movement labels are secondary explanatory annotations.

## Card and market-page layout

Overview cards should remain compact and pedagogical. A short technical interpretation should sit near the chart with layer toggles. On large screens the forecast graph may sit below the main card content if that gives the analysis text and toggles enough room.

The market detail page can expose richer controls, indicator detail, layer comparison, recipe metadata, confidence/uncertainty, and historical forecast evaluation.

## Data contract

Prefer v2 read models/workspace composition rather than direct SQL or recomputation in the UI. Relevant modules include `workspace_loader_v2.py`, `workspace_composer_v2.py`, `v2_technical_ui.py`, `technical_core_v2.py`, and the existing forecast visualization modules.

Do not trigger AI calls, Saxo calls, provider reads, or analysis recomputation merely because a user toggles a visualization layer.

## Performance principle

Expensive work happens once per input change. UI toggles should reuse cached layer outputs and recompute only cheap composition/geometry. Keep chart rendering deterministic for the same workspace + recipe.

## Pedagogical principle

PriceGauger should teach the user why the forecast looks the way it does. Indicator states and concise interpretation should be human-readable, but the UI must distinguish raw technical evidence from AI interpretation and from external context.

## Working protocol

Start from fresh `main`, one bounded capability per branch/PR. Preserve existing pages/layout unless a change clearly improves the v2 interaction. Add focused rendering/source tests. Avoid coupling visualization code to one specific instrument set.

## Immediate next priorities

1. Connect the read-only v2 Technical surface to production-like persisted data and verify useful empty/stale states.
2. Build a reusable v2 forecast chart component from `WorkspaceSnapshotV2` / composed forecast objects.
3. Add layer toggles with explicit recipe labeling and cached fast switching.
4. Add concise Technical Core / Technical Interpreter explanation beside the graph.
5. Add outcome/error visualization so baseline and refinement layers can be compared empirically.
6. Integrate the component into Overview cards and then the market detail page without breaking the current production UI.

## Out of scope

Do not change Technical Core weights, define new analysis layers, mutate DB state, or send trading orders. If the required visual information is missing, request a contract change from the owning analysis/database thread instead of inferring it in frontend code.
