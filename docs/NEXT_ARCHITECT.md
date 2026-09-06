# PriceGauger — Next Architect

Updated: 2026-09-07

The authoritative handoff for Arkitekt 10 is now:

**[`docs/ARCHITECT_HANDOFF_2026-09-07_ARKITEKT10.md`](ARCHITECT_HANDOFF_2026-09-07_ARKITEKT10.md)**

Read that document in full before changing AutoManager, LIVE OPEN/CLOSE, Saxo working-order handling, Strategy Series/Snapshot Spine, TradingDesk Lightweight charts, Spring evaluation, or futures rollover behavior.

## Starting point

Repository: `oveaignerhaukenes-lgtm/PriceGauger`

Runtime `main` immediately before this documentation handoff branch:

`07a464cc0fd57cfdb086270e8d8d83240d61a567`

That runtime baseline is PR #322 (**stale working-order / late-fill execution guard**) on top of the futures rollover hardening and the completed Lightweight TradingDesk/Strategy Lab migrations.

Final #322 CI: **1215 tests passed**.

Always refresh from current `main` before branching; the documentation merge itself will move `main` without changing runtime behavior.

## Immediate orientation

The highest-priority new execution fact is the September 7 market-reopen incident: an unexpected SHORT appeared broker-side while the active MACD strategy could not yet evaluate fresh bars. Production history showed persisted Friday SHORT transition authority, exposing a stale working-order/late-fill provenance weakness. PR #322 now adds market-open precheck, PG-owned working-order cleanup, unknown-order pause behavior, late-fill quarantine and persisted execution anomalies.

Do not restore unconditional AutoManager adoption of any exact Saxo position. Exposure state and execution provenance are now separate safety concerns.

TradingDesk LIVE and Strategy Lab/P&L charts now use TradingView Lightweight Charts as the canonical chart engine. Mobile X/Y scaling, pane and total-height resizing, persistence and compact timeframe controls have been physically tested by the user and work well.

Futures data rollover is implemented through immutable contract identities and audited collection switching. Brent rolled `43660942 -> 44297299`; Silver rolled `45184335 -> 46652614`. Rollover has no execution authority and must never silently mutate a LIVE controller UIC.

## Important open work

1. Verify #322 production guard state, Saxo working orders, exact position and `pg_v2_autotrader_execution_anomalies` before adding new execution UI.
2. PR #321 (**explicit Spring pane + wrapped legend**) is still open on an old base and is not in `main`; rebase/recreate it as presentation-only before merging.
3. Build the user-approved AutoTrader monitor: bottom-right `Armed LIVE` / green `AutoManage OFF`, position/P&L/provenance/strategy diagnostics, plus deterministic Pause/Start/Stop/Close semantics.
4. Add small red BUY / blue SELL quote buttons in the LIVE chart, showing current bid/ask so spread is visible, but route them through the existing `request_manual_target_v2()` lifecycle — never direct browser Saxo POST.
5. Add a generic Saxo futures discovery fallback for Natural Gas UIC `50419383`, which is stale but cannot yet be safely resolved through PrimaryListing.
6. Continue Spring observation and baseline comparison without inventing damping/absorption semantics before they are explicitly defined and versioned.
7. Diagnose the existing `sp500 CFD: invalid 5m ATR` as a source/canonical-bar data-quality issue; do not weaken the ATR validity gate.

Full invariants, exact incident timeline, #322 safety model, chart state, futures rollover semantics, Spring boundary, Railway identities and recommended work sequence are in the Arkitekt 10 handoff.
