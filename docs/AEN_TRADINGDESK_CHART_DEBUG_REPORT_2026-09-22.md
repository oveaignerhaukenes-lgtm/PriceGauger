# Aen – TradingDesk chart debugging report

**Date:** 2026-09-22  
**Scope:** TradingDesk live chart disappearance/crash investigation  
**Author:** Aen / ChatGPT

## Starting point

AutoTrader execution/authority was reported to be functioning again, while the TradingDesk live chart had disappeared. The visible chart containers/indicator panes existed, but price graphics were missing or collapsed. Work was deliberately isolated to chart/presentation code; no strategy, broker execution, or LIVE authority logic was intentionally changed.

## Relevant baseline

The live renderer is in:

- `tradingdesk_ui/charts/lightweight/direct_runtime.py`
- Lightweight Charts 5.2.1
- continuity wrapper: `tradingdesk_chart_runtime_continuity_v1.py`

A sequence of earlier hotfixes (#428–#438) had already addressed stable host, empty refreshes, viewport persistence, price-scale isolation, OHLC autoscale, diagnostics, explicit candle pane binding and collapsed price-pane recovery.

## Finding 1 – two competing definitions of the price pane

After #437/#438, candles and recovery code used the declared pane:

`paneIndex('price')`

but other renderer paths still assumed that the price pane was always pane 0. In particular, volume placement and pane stretch/layout logic used hard-coded pane 0 semantics.

That created an internal invariant violation: the renderer could declare price on one pane while sizing/overlay behavior treated another pane as price.

## Fix – PR #439

PR #439: **TradingDesk: enforce canonical live price pane**

Merged commit:

`2f450cf8e9a5c10f3bc3bbcc5f6d0a55f98246b8`

Changes:

- resolve `const pricePaneIndex = paneIndex('price')` once;
- bind candles to that canonical index;
- bind the volume overlay to the same price pane;
- use the canonical index for collapsed-pane recovery;
- allocate pane stretch by `pricePaneIndex`, not by assuming `panes[0]`;
- add regression coverage.

No trading/runtime authority semantics were changed.

### CI during #439

First CI exposed an overly literal new assertion. After correcting the implementation substitution, the next run exposed an older test that still required the pre-refactor literal `paneIndex('price')` call. That stale test was updated to assert the new canonical invariant.

Final PR CI passed before merge: **1521 tests passed**.

## Finding 2 – continuity module crashed after the renderer fix

After #439 deployed, TradingDesk failed at Python import with:

`RuntimeError: TradingDesk continuity patch anchor missing: saved pane ratios`

Trace path:

`pages/0_TradingDesk.py`
→ `tradingdesk_automanage_panel_v2.py`
→ `tradingdesk_chart_runtime_continuity_v1.py`
→ `install_chart_runtime_continuity_v1()`
→ `_replace_required(..., label="saved pane ratios")`

Root cause: `tradingdesk_chart_runtime_continuity_v1.py` does not call a stable renderer API for these modifications. It obtains `_runtime._DIRECT_LIVE_JS` as text and monkey-patches it with exact string replacements. #439 correctly changed the pane-layout source text, so the old exact `saved pane ratios` anchor no longer existed. The continuity installer treats a missing anchor as fatal, therefore TradingDesk crashed before the browser chart could be constructed.

This is independent of Saxo data and AutoTrader execution.

## Fix – PR #441

PR #441: **Fix TradingDesk continuity patch after price-pane invariant**

Merged commit:

`2a20d48c894fc1a40c5d6274e52885eb6b7edda3`

The continuity patch anchor was updated to match the canonical `pricePaneIndex` layout introduced by #439 while retaining `applySavedPaneGeometry(chart)`.

CI passed and Railway subsequently picked up commit `2a20d48c` for the PriceGauger services, including `pricegauger-web`.

## Architectural diagnosis

The immediate import crash is fixed by #441, but there is a deeper fragility in the chart architecture:

`tradingdesk_chart_runtime_continuity_v1.py` modifies a large JavaScript renderer by exact source-string replacement.

Consequences:

1. A semantically valid renderer refactor can break an unrelated continuity patch merely because source text changes.
2. Python unit tests can all pass for one layer while runtime installation of another patch fails after composition.
3. Repeated hotfixes can accumulate implicit ordering dependencies between patches.
4. Debugging becomes misleading: symptoms appear as missing candles, collapsed panes, stale viewport or complete TradingDesk failure even when canonical market data is healthy.
5. The current `_replace_required` fail-fast behavior is useful for detecting drift, but because installation happens during module import it converts presentation-contract drift into a full page outage.

## Recommended next architectural step

Do not continue indefinitely adding exact-string hotfixes to `_DIRECT_LIVE_JS`.

The renderer should expose explicit stable extension/configuration points for:

- geometry persistence/restoration;
- wrapper reparenting/continuity;
- idle refresh behavior;
- marker styling;
- pane allocation;
- viewport persistence.

Preferably these should live directly in the canonical renderer rather than being injected later by textual substitution. If a compatibility layer must remain temporarily, it should be tested against the fully composed runtime in CI, not only against isolated source literals.

A useful regression test should import the same module chain as the production TradingDesk page so that a missing continuity anchor fails CI before deployment.

## Current state at handoff

- #439 merged: canonical price-pane invariant.
- #441 merged: continuity patch made compatible with #439.
- GitHub CI for #441 succeeded.
- Railway detected merged commit `2a20d48c` and began deployments for `pricegauger-web`, worker, stream and Spring-Trade-Engine.
- No intentional changes were made to AutoTrader strategy semantics, LIVE authority, broker reconciliation, or Saxo execution.
- The next verification should be the deployed TradingDesk itself: confirm page imports, then confirm candles/price pane render, then confirm continuity across periodic refresh and pan/zoom.
