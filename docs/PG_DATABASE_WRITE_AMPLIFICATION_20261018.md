# PriceGauger: production database write-amplification, first safe fix (2026-10-18)

Current measured 24h average by Railway:
- PostgreSQL 0.900 vCPU, 2.165 GB RAM, 11.37 GB disk.
- PriceGauger-stream 0.644 vCPU, 0.306 GB RAM.
- PriceGauger-worker 0.440 vCPU, 0.502 GB RAM.
Other three combined about 0.017 vCPU.

These are total workloads, not direct estimates of bar storage costs.

## Observed duplication
\`RealtimeMarketDataStore.save_bar()\` writes a compatibility
\`realtime_bars_1m\` row then a canonical \`pg_v2_market_bars_1m\` row.
On Saxo backfill, gap repair or duplicate receipt, both use
\`ON CONFLICT ... DO UPDATE\` even when the values are unchanged. This causes
avoidable row writes, WAL, vacuum and index activity. Canonical quality flags
must be treated as real data: realtime vs backfill is NOT interchangeable.

## Fix
Both conflict UPSERTs use \`IS DISTINCT FROM\` comparisons and skip no-op
updates. All inserts still occur; a revised OHLC, volume (including NULL vs
0), UIC, complete JSON record or quality flag updates immediately. No
order execution, broker API, risk controls, strategy, schema migration,
index, polling cadence or deployments are modified.

The \`IS DISTINCT FROM\` operator is null-safe, supported by PostgreSQL and
modern SQLite. Tests exercise repeated data, corrected OHLC/volume, and
backfill quality-flags under real isolated SQLite storage and prove that
the UPDATE trigger is not fired for identical values.

### Verification needed
- Check Github CI and Railway status after deploy.
- Collect **after** Railway CPU and DB metrics over comparable trading/
  non-trading periods; do not claim a percentage saving from code alone.
- Before a larger optimisation, profile query frequency, pg_stat_statements
  (read-only, without enabling extensions on production blindly) and the
  unnecessary Natural Gas shadow failures seen when there is no canonical
  history. Shadow loops may be optimized separately, never pause Saxo risk,
  close, account reconciliation or LIVE supervision.
