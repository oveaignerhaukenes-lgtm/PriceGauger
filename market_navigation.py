from __future__ import annotations

from urllib.parse import quote


def market_detail_href(market: str) -> str:
    """Route a market-card click through the app entrypoint.

    The app shell then uses ``st.switch_page`` after registering the explicit
    ``st.navigation`` tree. This prevents direct page loads from falling back
    to Streamlit's legacy automatic pages menu.
    """
    return f"/?open_market={quote(str(market), safe='')}"
