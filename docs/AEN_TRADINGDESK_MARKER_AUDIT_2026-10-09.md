# TradingDesk V3 execution triangle audit — 2026-10-09

## Scope / non-interference

Read current `docs/AEN_ARCHITECT_HANDOFF_2026-10-09.md` and inspected production (Railway web + worker on `168f04b4094c5fee8d534e28a670e8db0d9e4651` at investigation time). This branch is isolated from the parallel strategy development. No strategy semantics, armed state, Saxo accounts, order authority, or reconciliation changed. This PR is **not deployed** until explicitly merged.

## Actual production presentation path

`pages/0_TradingDesk.py`
→ `_load_standalone_chart_payload()`
→ `load_lightweight_trade_markers_v1()` (adapter with 3-second Streamlit cache)
→ `load_autotrader_trade_markers_v2()` (source-isolated aggregation)
→ `load_v3_trade_markers_v1()` (read-only reconciled V3 event projection)
→ `build_lightweight_direct_live_payload_v1()`
→ `contract._marker_payload()`
→ **`render_lightweight_simple_live_v2()`** for BOTH initial chart and 1-second fragment refreshes.

Earlier fixes/tests focused on `trade_marker_overlay_v2.py` and `live_update.py`, but those are not the active TradingDesk renderer. This left two regressions undetected.

## Confirmed code defect A — broker-side arrows overwritten

`contract._marker_payload()` correctly encodes V3 execution `side`: BUY → `arrowUp`, SELL → `arrowDown`, with account palette, per-action size, unique request key and `marker_role='EXECUTION_EVENT'`.

However BOTH JavaScript paths in `simple_live_v2.py` remap every marker's `shape`, `position` and FLAT color using **resulting inventory direction**, not execution side:

- SELL to reduce still-LONG inventory becomes an up arrow (wrong).
- BUY to close SHORT (result FLAT) becomes a neutral square (loses BUY arrow).
- Reconciled V3 execution shape and color from canonical contract become presentation-dependent.
- The identical override happens on each 1-second refresh.

**Fix:** pass through `source='AUTOTRADER_V3'` markers without rewriting. Keep existing legacy/manual/V2 marker handling.

## Confirmed code defect B — oldest 1000 selected

`autotrader_v3_trade_markers_v1.load_v3_trade_markers_v1` queried the 14-day event ledger with:

```sql
ORDER BY e.executed_at ASC LIMIT 1000
```

When the event count crosses 1000, this permanently omits every newer event until enough old events age out. This is directly contrary to an actively trading live chart's needs.

**Fix:** take most recent 1000 (`DESC, request_key DESC`) and restore chronological order in memory for downstream consumers.

The 1000-event saturation **is a conditional failure mode, not confirmed production volume**: Railway logging does not expose the ledger row count. Count should be verified with a read-only query if missing recent events persist after deployment.

## Simultaneous markers and limits of the diagnosis

Backend `contract._marker_payload()` retains each execution as a distinct event with unique `id` even when multiple accounts trade in the same candle. It does NOT explicitly de-duplicate by time, account or side. Markers from different accounts share the same candle `time`, so Lightweight Charts decides the final visual stacking/spacing. Without an authenticated browser session/real chart render, visual occlusion cannot be ruled out; a fixture-based multi-account same-candle test was added.

The chart also clips events outside the displayed candle window (with a one-timeframe grace). Therefore historical 14-day ledger retention does not imply 14 days visible on a 12-hour chart. This is expected behavior, not the primary fix.

Other possible issues *not addressed here*:
- `manual_saxo_trade_markers_v1._active_products_v1` discovers only active V2 enrollments. Manual Saxo trades on accounts owned exclusively by V3 may not be ingested; this affects 'M' labels, not confirmed V3 execution arrows.
- The V3 projection joins each event to an instance row; deletion/identity drift may hide historical markers. No evidence of such drift from available logs.
- Failed/blocked or unreconciled orders correctly should not generate confirmed execution triangles.
- No complete event-count or browser-pixel verification was available from current connector scopes.

## Validation / roll-out

1. Run full GitHub Actions pytest; validate added active-path regressions.
2. Keep this PR separate from parallel strategy work; recheck fresh `main` before merge.
3. Merge only after CI. Verify web Railway SHA is the merge SHA; do not redeploy an older build.
4. In TradingDesk select Tech100 and a candle interval containing known confirmed executions. Check simultaneous BUY and SELL markers across at least three account colors, especially a SELL reduction that leaves LONG and a BUY close to FLAT.
5. If missing recent events remain, compare read-only per-source counts: `autotrader_v3_execution_events` market/last-14-days/last-24-hours, projection count, JSON payload marker count, browser setMarkers count, and available candle time range.
6. Separate incident: investigate unique request-key violations observed in worker logs around 08:34 UTC 2026-10-09; they are execution-level errors and not proven to explain chart-only issues.

No LIVE execution switches or Saxo orders are needed to verify the presentation fix.
