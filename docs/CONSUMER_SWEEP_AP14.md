# AP14 — v2 consumer sweep before UI test window

AP14 freezes the migration boundary before the first broader production/UI test window.

## CUTOVER

The following production consumers must not query legacy market-history/state tables directly:

- Technical Core live runtime
- parallel forecast outcome runtime
- AutoTrader 30m MACD dry-run
- TradingDesk analysis/forecast workspace
- Overview technical/forecast cards

Market-history consumers share `MarketHistoryStore`, whose PostgreSQL preference is `pg_v2_market_bars_1m`. TradingDesk reads the canonical v2 workspace and explicitly refuses hidden legacy analysis/forecast fallback.

## TEMPORARY ADAPTER

Two compatibility seams remain intentionally:

1. `MarketHistoryStore` may merge pre-cutover technical snapshots / legacy realtime rows to fill historical gaps where v2 physical history does not yet exist. A same-timestamp v2 bar wins.
2. `RealtimeMarketDataStore` still dual-writes `realtime_bars_1m` during the initial production test window for rollback and old diagnostics. PostgreSQL latest/range reads prefer v2.

These are migration adapters, not alternative production authorities.

## MIXED SURFACE

Overview remains intentionally mixed outside the technical cards: its existing semantic/news/event shell is still fed by legacy semantic stores while canonical Context v2 is produced side-by-side. This is visible architectural debt, not permission for legacy technical authority to return.

## RETIRE

Historical Event Lab remains an isolated legacy developer surface. It is not production authority and belongs to the later legacy-retirement capability.

## Gate

`tests/test_consumer_cutover_manifest_v2.py` prevents authoritative runtime/UI consumers from reintroducing direct reads of known legacy market-history, decision, or recommendation tables. The manifest makes each surviving boundary explicit as CUTOVER, TEMPORARY_ADAPTER, MIXED_SURFACE, or RETIRE.

Deletion of rollback tables is deliberately deferred until the site has been exercised against live v2 data and canonical history coverage is verified.
