# Parallel-agent handoff — TradingDesk live chart refresh and AutoTrader trade arrows
Date: 2026-09-28
Owner: separate chart/presentation agent
Base at handoff: main `1dfd8c9008d9de0ace9b1346e3f3273677019ec6` (#534). Re-fetch main before coding.

## Mission
Fix the TradingDesk live Lightweight Charts experience so the currently forming candle updates visibly at approximately one-second cadence without remounting the main chart, losing pan/zoom or collapsing indicator panes. Display durable AutoTrader LONG/SHORT execution arrows and confirmed FLAT markers at the correct time/price. Keep the chart usable during idle periods, refreshes, timeframe changes and mobile interaction.

**Strict scope: chart/data projection, markers, chart refresh and tests only.** Do not modify Saxo order submission, account selection, strategy authority, V2/V3 motor selection, strategy-family configuration, execution/reconciliation, live gates, or existing positions. Never place a real Saxo order to test the chart. Coordinate any necessary contract change with the main V2 agent first.

## Parallel work — avoid conflict
The main agent has a separate, unmerged branch `aen/v2-single-live-authority` to make the upper Posisjon og AutoTrade switch the sole LIVE authority and turn Strategifamilie into family/timeframe configuration that preserves authority. **Do not cherry-pick, reimplement or edit its files.** In particular, avoid `tradingdesk_strategy_family_ui_v1.py` and `tradingdesk_automanager_simple_v1.py`. Your work should remain a clean chart-only PR from fresh main.

Recent #534 restored V2 account/strategy display safety, while V3 compatibility code remains present. The chart must not infer which motor owns broker authority from a display label.

## Start here
- `pages/0_TradingDesk.py` — production chart integration and refresh cadence constants (`LIVE_CANDLE_OVERLAY_REFRESH_SECONDS = 1`, `TRADINGDESK_CHART_REFRESH_SECONDS = 1`); loads chart payload and trade markers.
- `pages/0_Live_Chart.py` — minimal 1-second live chart test, **without** AutoTrader/indicators. Use as the control case to isolate TradingDesk integration vs data feed.
- `tradingdesk_ui/charts/lightweight/direct_contract.py` — canonical payload contract.
- `tradingdesk_ui/charts/lightweight/direct_runtime.py` — canonical JS renderer, pane/series registry and forming candle update.
- `tradingdesk_ui/charts/lightweight/simple_live_v2.py` — current render/refresh wrapper.
- `tradingdesk_ui/charts/lightweight/live_test_snapshot_v1.py` and `saxo_chart_live.py` — canonical closed bars + forming candle snapshot.
- `tradingdesk_ui/charts/lightweight/live_update.py` and `live_update_refresh_v2.py` — legacy updater and revision-key remount workaround.
- `tradingdesk_ui/charts/lightweight/trade_marker_overlay_v2.py` — marker overlay; retries after updater at 0/80/240/700 ms, suggesting a race between independent marker writers.
- `tradingdesk_ui/charts/lightweight/adapters.py`, `autotrader_trade_markers_v1.py`, `autotrader_trade_markers_v2.py`, `manual_saxo_trade_markers_v1.py` — marker source and adapter. V2 projects reconciled CLOSE as FLAT square using nearest 1m bar close within 10 minutes; that is an **approximate presentation price**, not broker execution price.
- `tradingdesk_chart_runtime_continuity_v1.py` and `docs/AEN_TRADINGDESK_CHART_DEBUG_REPORT_2026-09-22.md` — historical price-pane/continuity failure and fragility from exact-string JS monkey patches.

## Known hazards to investigate, not assume fixed
1. Previous TradingDesk symptoms: chart host and indicator panes visible, but candles/indicators absent or a green/red dotted line; stale forming candle despite Live Chart test working. Validate current production state rather than assuming old symptoms persist.
2. Two chart writers can update markers: the legacy live updater's `markerPayload` accepts LONG/SHORT, while the V2 overlay adds FLAT and retries to win scheduling races. Establish **one canonical marker writer** so refreshes cannot erase FLAT squares or arrows.
3. A payload-derived Streamlit component key remounts the zero-height updater when candle/marker revision changes. Verify this updates the existing chart registry entry rather than remounting the main chart; avoid viewport and geometry reset.
4. Exact-source monkey patches in the continuity module can fail on harmless renderer refactors, crashing TradingDesk at import. Test the fully composed production import/renderer chain before merge; prefer stable extension hooks over additional string substitutions.
5. Canonical price pane index must be used consistently for candles, volume, layout, recovery and markers. Do not reintroduce pane-0 assumptions.
6. Marker identity/timeframe: deduplicate durable OPEN/CLOSE events; map execution timestamps to chart candles without misplacing arrows at bucket edges or silently discarding out-of-window events. Account/product and position provenance must remain explicit where available. Distinguish AUTO LONG/SHORT, manual Saxo fills and confirmed FLAT in legend/tooltips.

## Execution plan
1. Establish a reproducible baseline in `pages/0_Live_Chart.py` and TradingDesk on the same instrument/timeframe. Record closed-bar timestamp, forming candle timestamp/source age, refresh tick and marker count, without exposing Saxo secrets.
2. Trace one update end-to-end: Saxo feed → forming store/snapshot → direct payload → Streamlit fragment → JS registry → `candles.update`. Diagnose whether missing updates originate in data freshness, fragment rerun, component reconciliation, chart registry, or JS error. Explicitly distinguish stale upstream data from broken rendering.
3. Trace one **existing, reconciled** AutoTrader trade end-to-end: durable source → marker adapter → payload → JS `setMarkers` → visible arrow; similarly trace confirmed FLAT. Do not create live trades for tests.
4. Consolidate marker updates into a single canonical writer with deterministic ordering, stable IDs, correct bucket mapping and no duplicate/racing overlays. Keep the main chart mounted across refreshes; preserve pan/zoom and pane geometry.
5. Add focused Python contract/adapter tests plus JS/source-composition tests for registry update, stale-data behavior, marker deduplication, FLAT persistence, empty payload, timeframe changes, no trade history, and import of the production TradingDesk module chain.
6. Run compileall, focused tests and full pytest suite. Open a **chart-only PR**, monitor CI, merge only when green and follow Railway web/worker/stream/Spring Trade Engine to SUCCESS. Browser-smoke-test TradingDesk and Live Chart at 1m and 5m; report separately what was visually verified vs only covered by tests.

## Acceptance criteria
- TradingDesk forming candle visibly updates on incoming data at ~1s cadence, including correct high/low changes; stale feed is reported as stale, not faked.
- Historical bars do not flicker, duplicate or disappear during updates; chart keeps current zoom/pan and indicator pane sizes.
- Existing durable AutoTrader LONG/SHORT fills show one correctly directed arrow each; confirmed FLAT shows a neutral square; manual Saxo fills are distinguishable. No presentation marker is mistaken for an executable order.
- Marker set survives successive forming-candle refreshes and timeframe switches, with no updater/overlay race.
- Standalone Live Chart and TradingDesk show consistent market data for the same instrument/timeframe.
- No change to V2/V3 authority, enrollment, account binding, order execution or risk controls.

## Handoff deliverables
Record root cause(s), exact changed files, tests/results, PR and merged commit, Railway deployments, screenshots/browser observations and any remaining caveats in a chart-specific feature report under `docs/`. If no approved/reconciled trade is available to visualize in production, use deterministic fixture-based browser tests and state explicitly that production arrows remain unverified.
