from __future__ import annotations

"""Presentation projection of canonical V3 execution events."""

from autotrader_trade_markers_v1 import AutoTraderTradeMarkerV1
from autotrader_v3_order_guard_v1 import ensure_schema as ensure_v3_order_schema
from database import connect, using_postgres


def load_v3_trade_markers_v1(market_name: str) -> tuple[AutoTraderTradeMarkerV1, ...]:
    if not using_postgres():
        return ()
    ensure_v3_order_schema()
    with connect() as db:
        rows=db.execute("""SELECT e.executed_at,anchor.close AS display_price,e.direction,e.amount,
            e.instance_id,e.request_key
          FROM autotrader_v3_execution_events e
          JOIN autotrader_v3_engine_instances i ON i.instance_id=e.instance_id
          JOIN LATERAL (
            SELECT b.close FROM pg_v2_market_bars_1m b
            WHERE b.instrument_id=i.instrument_id AND b.bar_time<=e.executed_at
            ORDER BY b.bar_time DESC LIMIT 1
          ) anchor ON TRUE
          WHERE e.market_name=? AND e.executed_at>=now()-INTERVAL '14 days'
          ORDER BY e.executed_at ASC LIMIT 1000""",(str(market_name),)).fetchall()
    result=[]
    for row in rows:
        v=dict(row) if isinstance(row,dict) else dict(zip(("executed_at","display_price","direction","amount","instance_id","request_key"),row))
        result.append(AutoTraderTradeMarkerV1(
            executed_at=v["executed_at"],execution_price=float(v["display_price"]),
            direction=str(v["direction"]),amount=float(v["amount"]),
            strategy_key=str(v["instance_id"]),net_position_id=str(v["request_key"]),
            active=False,source="AUTOTRADER_V3"))
    return tuple(result)


__all__ = ["load_v3_trade_markers_v1"]
