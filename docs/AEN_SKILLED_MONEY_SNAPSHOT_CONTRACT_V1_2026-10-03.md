# Skilled Money snapshot contract v1 — 2026-10-03

Skilled Money is a retrospective learning surface. It may later persist compact analyses, but is not an AutoTrader input.

## Event lifecycle
1. A notable market move creates an event snapshot.
2. T0 revision records only information available at that time.
3. Later releases (options/OI, ETF flows, CFTC/COT, holdings, central-bank/reserve reports, etc.) append revisions.
4. Old revisions are never overwritten.
5. Claims are classified as OBSERVED, INFERRED, CONFIRMED, WEAKENED or REFUTED.

## Storage principle
Store compact causal snapshots and provenance, not bulk copies of raw feeds. Keep enough measured values and source/timing metadata to reproduce why an interpretation was made.

## Execution boundary
No V2/V3 strategy target, sizing, execution or reconciliation code may depend on Skilled Money snapshots without a later explicit architecture decision and separate integration.
