from __future__ import annotations

from collections.abc import Sequence

from autotrader_trade_markers_v1 import AutoTraderTradeMarkerV1, load_autotrader_trade_markers_v1


def load_lightweight_trade_markers_v1(market: str) -> Sequence[AutoTraderTradeMarkerV1]:
    """Read-only adapter from the durable AutoTrader marker projection.

    Presentation only: this adapter cannot create requests, alter positions, or call Saxo.
    """

    return load_autotrader_trade_markers_v1(str(market))


__all__ = ["load_lightweight_trade_markers_v1"]
