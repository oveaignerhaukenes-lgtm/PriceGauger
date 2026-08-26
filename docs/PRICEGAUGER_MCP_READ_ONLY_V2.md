# PriceGauger read-only MCP v2

## Purpose

Expose PriceGauger's canonical v2 market data to an MCP client without exposing Saxo credentials or any trading/execution capability.

The boundary reads `pg_v2_market_bars_1m` through the existing canonical v2 store. Saxo authentication, order placement, amendment, cancellation and position-management modules are deliberately outside this capability.

## Tools

- `list_markets()` — enabled v2 collection subscriptions and canonical instrument identity.
- `get_market_snapshot(market)` — latest canonical 1m OHLCV bar plus age/staleness metadata.
- `get_candles(market, horizon_minutes, count)` — 1/5/15/30/60 minute OHLCV candles aggregated from canonical 1m bars. `count` is capped at 500.

Every market-data response identifies its source as `pricegauger_canonical_v2` and reports `execution_capability: false`.

## Run locally

Install project requirements, configure PriceGauger's normal PostgreSQL connection and optionally set:

```bash
PRICEGAUGER_DB_PATH=pricegauger.db
PRICEGAUGER_MCP_STALE_AFTER_SECONDS=180
```

Then run:

```bash
python pricegauger_mcp.py
```

The default MCP transport is stdio. For a remote ChatGPT/App connection, deploy the same server using MCP's Streamable HTTP transport behind authentication/TLS; do not expose an unauthenticated endpoint to the public internet.

## Security boundary

This first capability is intentionally one-way:

`Saxo runtime -> PriceGauger canonical v2 store -> ExternalMarketReadServiceV2 -> MCP client`

There is no reverse path into Saxo execution. Any future execution integration must be a separate capability and PR with explicit authorization, policy gates and audit logging.

## Next extension

Once this read-only boundary is deployed and connected, higher-level read tools can be added independently for persisted technical state, forecast/workspace state and macro snapshots while preserving the same no-execution rule.
