from __future__ import annotations

from urllib.parse import quote


def market_detail_href(market: str) -> str:
    """Return the internal Markedsvisning route for one market."""
    return f"/Forecast_Learning?market={quote(str(market), safe='')}"
