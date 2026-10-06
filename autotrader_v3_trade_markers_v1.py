from __future__ import annotations

"""Presentation projection of canonical V3 execution events."""

from autotrader_trade_markers_v1 import AutoTraderTradeMarkerV1
from autotrader_v3_execution_events_v1 import load_execution_events_v1
from database import using_postgres


def load_v3_trade_markers_v1(market_name: str) -> tuple[AutoTraderTradeMarkerV1, ...]:
    if not using_postgres():
        return ()
    return tuple(
        AutoTraderTradeMarkerV1(
            executed_at=event.executed_at,
            execution_price=0.0,
            direction=event.direction,
            amount=event.amount,
            strategy_key=event.instance_id,
            net_position_id=event.request_key,
            active=False,
            source="AUTOTRADER_V3",
        )
        for event in load_execution_events_v1(str(market_name))
    )


__all__ = ["load_v3_trade_markers_v1"]
