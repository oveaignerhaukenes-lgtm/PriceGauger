# MTF 30/10/5 short/flat — LIVE v1

This capability mirrors the reviewed MTF long/flat hierarchy on the bearish side while preserving the existing AutoManager execution boundary.

## Signal policy

- 30m closed MACD context: BEARISH or DETERIORATING permits an early short attempt.
- 5m closed MACD CROSS_DOWN requests provisional SHORT.
- 10m closed bearish MACD validates; a bullish reversal rejects and requests FLAT.
- 30m closed CROSS_DOWN confirms the short regime; CROSS_UP ends it and requests FLAT.
- Bootstrap adopts actual Saxo SHORT/FLAT exposure and advances all current cursors with `BOOTSTRAP_NO_REPLAY`.
- Outage/stale bars advance cursors without replaying historical order authority.

## Execution boundary

The MTF short runtime never calls Saxo order POST. It persists ordinary `pg_v2_autotrader_execution_requests` only. OPEN and CLOSE remain handled by the existing hardened executors, including direction-specific Product Admission, Margin Envelope, sizing, final Saxo precheck, durable attempt-before-POST, uncertain-submit handling and reconciliation.

## Strategy switching

Strategy cohorts remain product+strategy specific. A switch:

- first quiesces old OPEN authority;
- requires exact Saxo FLAT and no working order for the product;
- requires settled source close/P&L provenance when the source cohort has exposure history;
- creates target equity, enrollment and copied Margin Envelope atomically in FK-safe order;
- starts the target with an empty position anchor and LIVE OPEN disarmed;
- records a settled-FLAT handoff event so only the target cohort's first OPEN may inherit source FLAT provenance;
- after the target has submitted an OPEN, ordinary target-cohort settled-close provenance is required for later re-entry.

Immediately before any LIVE OPEN durable submit, PriceGauger now rechecks global and pilot authority, request freshness/currentness, actual Saxo exposure and working orders after the final sizing/precheck step.

## Activation

Switching to the strategy does not itself place an order. SHORT entry additionally requires explicit SHORT Product Admission and user-confirmed NBP/limited-loss safety in TradingDesk. LIVE OPEN must then be armed explicitly.
