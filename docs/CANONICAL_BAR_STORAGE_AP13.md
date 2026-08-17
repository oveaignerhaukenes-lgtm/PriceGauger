# AP13 — canonical 1m bar storage cutover

`pg_v2_market_bars_1m` becomes the canonical PostgreSQL physical store for subscribed v2 market instruments.

## Write path

Completed Saxo realtime and repaired chart bars still pass through `RealtimeMarketDataStore` so the streaming service does not fork into a second ingestion pipeline. On PostgreSQL the store resolves the bar UIC through the active subscribed v2 instrument registry and upserts the same OHLCV into `pg_v2_market_bars_1m`, keyed by `(instrument_id, bar_time)`.

The old `realtime_bars_1m` row is temporarily dual-written during AP13 for rollback and remaining legacy consumers. It is no longer the preferred PostgreSQL read source.

## Read path

`MarketHistoryStore` merges historical technical snapshots, compatibility realtime rows, then v2 canonical bars in that order. A v2 bar therefore wins at an identical timestamp. This preserves older history that predates the cutover while moving live Technical Core, forecast outcome resolution and AutoTrader dry-run onto the v2 physical source through their existing `MarketHistoryStore` contract.

`RealtimeMarketDataStore` latest/range reads likewise prefer v2 bars on PostgreSQL and fall back only when no v2 rows exist for the requested range.

## Identity and quality

Canonical writes require an active subscribed Saxo v2 source and exact provider UIC match. Realtime-completed bars use `QUALITY_REALTIME`; gap-repair/chart bars use `QUALITY_BACKFILL`.

## Deferred

AP13 does not delete `realtime_bars_1m`, remove technical-snapshot historical fallback, alter forecast math, change AutoTrader strategy semantics, or retire legacy UI/runtime. Those belong to the later consumer sweep and legacy-retirement capabilities after production cutover is observed.
