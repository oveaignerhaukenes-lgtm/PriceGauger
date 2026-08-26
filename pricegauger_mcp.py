from __future__ import annotations

import os

from external_market_read_v2 import ExternalMarketReadServiceV2

try:
    from mcp.server import MCPServer
except ImportError as exc:  # pragma: no cover - deployment/configuration failure
    raise RuntimeError(
        "PriceGauger MCP requires the 'mcp' package. Install project requirements first."
    ) from exc


DB_PATH = os.getenv("PRICEGAUGER_DB_PATH", "pricegauger.db")
STALE_AFTER_SECONDS = int(os.getenv("PRICEGAUGER_MCP_STALE_AFTER_SECONDS", "180"))

service = ExternalMarketReadServiceV2(
    DB_PATH,
    stale_after_seconds=STALE_AFTER_SECONDS,
)

mcp = MCPServer(
    "PriceGauger Market Data",
    instructions=(
        "Read-only PriceGauger market-data server. Data comes from the canonical v2 "
        "store populated by PriceGauger's Saxo runtime. This server has no order/execution tools."
    ),
)


@mcp.tool()
def list_markets() -> list[dict]:
    """List enabled canonical PriceGauger v2 market subscriptions."""
    return service.list_markets()


@mcp.tool()
def get_market_snapshot(market: str) -> dict:
    """Return the latest canonical 1-minute OHLCV bar and freshness metadata."""
    return service.snapshot(market)


@mcp.tool()
def get_candles(
    market: str,
    horizon_minutes: int = 1,
    count: int = 120,
) -> dict:
    """Return up to 500 canonical candles aggregated from PriceGauger 1m bars."""
    return service.candles(
        market,
        horizon_minutes=horizon_minutes,
        count=count,
    )


if __name__ == "__main__":
    mcp.run()
