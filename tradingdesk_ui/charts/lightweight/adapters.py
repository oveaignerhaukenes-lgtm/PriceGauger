from __future__ import annotations

from collections.abc import Sequence

import streamlit as st

from autotrader_trade_markers_v1 import AutoTraderTradeMarkerV1, load_autotrader_trade_markers_v1


@st.cache_data(ttl=3, show_spinner=False)
def load_lightweight_trade_markers_v1(market: str) -> Sequence[AutoTraderTradeMarkerV1]:
    """Read-only adapter from the durable AutoTrader marker projection.

    Presentation only: this adapter cannot create requests, alter positions, or call Saxo.
    The short cache avoids a database read on every one-second forming-candle refresh.
    """

    return tuple(load_autotrader_trade_markers_v1(str(market)))


__all__ = ["load_lightweight_trade_markers_v1"]
