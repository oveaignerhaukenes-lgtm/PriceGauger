from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

import streamlit as st

from autotrader_trade_markers_v1 import AutoTraderTradeMarkerV1
from autotrader_trade_markers_v2 import load_autotrader_trade_markers_v2
from autotrader_v3_live_saxo_v1 import configured_live_pilot_client_v3


@st.cache_data(ttl=30, show_spinner=False)
def _account_names_v1() -> dict[str, str]:
    broker = configured_live_pilot_client_v3()
    if broker is None:
        return {}
    try:
        rows = broker.accounts()
    except Exception:
        return {}
    result: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        account_id = str(row.get("AccountId") or "").strip()
        if not account_id:
            continue
        result[account_id] = str(
            row.get("AccountName") or row.get("DisplayName") or account_id
        ).strip()
    return result


@st.cache_data(ttl=3, show_spinner=False)
def load_lightweight_trade_markers_v1(market: str) -> Sequence[AutoTraderTradeMarkerV1]:
    """Read-only adapter from the durable AutoTrader marker projection.

    Presentation only: this adapter cannot create requests, alter positions, or call Saxo.
    The short cache avoids a database read on every one-second forming-candle refresh.
    """

    names = _account_names_v1()
    return tuple(
        replace(
            marker,
            account_name=names.get(str(marker.account_id), marker.account_name),
        )
        for marker in load_autotrader_trade_markers_v2(str(market))
    )


__all__ = ["load_lightweight_trade_markers_v1"]
