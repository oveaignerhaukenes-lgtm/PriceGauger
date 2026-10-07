from __future__ import annotations
"""Presentation projection of canonical V3 execution events."""
from collections import defaultdict

from autotrader_trade_markers_v1 import AutoTraderTradeMarkerV1
from autotrader_v3_order_guard_v1 import ensure_schema as ensure_v3_order_schema
from database import connect,using_postgres


def marker_direction_v3(*,action:str,side:str,resulting_direction:str)->str:
    """Execution-side direction for the small BUY/SELL marker."""
    action_u=str(action or "").upper()
    side_u=str(side or "").upper()
    result_u=str(resulting_direction or "").upper()
    if action_u=="CLOSE" and result_u=="FLAT":
        return "FLAT"
    if side_u=="BUY":
        return "LONG"
    if side_u=="SELL":
        return "SHORT"
    return result_u


def position_direction_v3(*,inventory_after:float,resulting_direction:str)->str:
    """Net position direction after the execution."""
    value=float(inventory_after)
    if abs(value)<=1e-12:
        return "FLAT"
    if value>0:
        return "LONG"
    if value<0:
        return "SHORT"
    return str(resulting_direction or "").upper()


def _position_quanta_v3(rows)->dict[str,float]:
    """Use the smallest observed reconciled amount per instance as one visual tranche."""
    amounts:dict[str,list[float]]=defaultdict(list)
    for row in rows:
        v=dict(row) if isinstance(row,dict) else dict(zip(
            ("executed_at","display_price","action","side","direction","amount",
             "inventory_before","inventory_after","instance_id","request_key"),row))
        try:
            amount=abs(float(v["amount"]))
        except (TypeError,ValueError):
            continue
        if amount>1e-12:
            amounts[str(v["instance_id"])].append(amount)
    return {
        instance_id:min(values)
        for instance_id,values in amounts.items()
        if values
    }


def load_v3_trade_markers_v1(market_name:str)->tuple[AutoTraderTradeMarkerV1,...]:
    if not using_postgres():return ()
    ensure_v3_order_schema()
    with connect() as db:
        rows=db.execute("""SELECT e.executed_at,anchor.close AS display_price,
          e.action,e.side,e.direction,e.amount,e.inventory_before,e.inventory_after,
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

    quanta=_position_quanta_v3(rows)
    result=[]
    keys=("executed_at","display_price","action","side","direction","amount",
          "inventory_before","inventory_after","instance_id","request_key")
    for row in rows:
        v=dict(row) if isinstance(row,dict) else dict(zip(keys,row))
        after=float(v["inventory_after"])
        quantum=quanta.get(str(v["instance_id"]))
        units=(abs(after)/quantum) if quantum and quantum>1e-12 else None
        result.append(AutoTraderTradeMarkerV1(
            executed_at=v["executed_at"],
            execution_price=float(v["display_price"]),
            direction=position_direction_v3(
                inventory_after=after,
                resulting_direction=str(v["direction"]),
            ),
            amount=float(v["amount"]),
            strategy_key=str(v["instance_id"]),
            net_position_id=str(v["request_key"]),
            active=False,
            source="AUTOTRADER_V3",
            action=str(v["action"]),
            side=str(v["side"]),
            inventory_before=float(v["inventory_before"]),
            inventory_after=after,
            position_units=float(units) if units is not None else None,
        ))
    return tuple(result)


__all__=[
    "marker_direction_v3",
    "position_direction_v3",
    "load_v3_trade_markers_v1",
]
