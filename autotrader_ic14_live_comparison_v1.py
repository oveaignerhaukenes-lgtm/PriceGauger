"""Same-window historical observations, never inferred fills or historical settings."""
from collections import Counter
from datetime import datetime,timezone
from database import connect

def utc(value):
    d=value if isinstance(value,datetime) else datetime.fromisoformat(str(value).replace("Z","+00:00"))
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)

def load_evidence(*,trader_id,key,start,end,db_path="pricegauger.db"):
    with connect(db_path) as db:
        signals=db.execute("""SELECT quote_at,action,source_mid FROM pg_v3_impulse_signal_events
            WHERE trader_id=? AND strategy_key=? AND quote_at>=? AND quote_at<=?
            ORDER BY quote_at LIMIT 4001""",(str(trader_id),key,utc(start).isoformat(),utc(end).isoformat())).fetchall()
        executions=db.execute("""SELECT executed_at,action,side,amount,inventory_before,inventory_after,
            account_id,broker_order_id
            FROM autotrader_v3_execution_events WHERE instance_id=? AND uic=4912 AND asset_type='CfdOnIndex'
            AND executed_at>=? AND executed_at<=? ORDER BY executed_at LIMIT 4001""",
            (str(trader_id),utc(start).isoformat(),utc(end).isoformat())).fetchall()
        state=db.execute("""SELECT strategy_key,last_quote_at,updated_at FROM pg_v3_tick_live_state
            WHERE trader_id=?""",(str(trader_id),)).fetchone()
    if len(signals)>4000 or len(executions)>4000:
        raise ValueError("evidence limit")
    # Optional archive only; no broker request and no schema creation here.
    # Join using the complete account/product/order identity, never order ID alone.
    fills=None
    try:
        with connect(db_path) as db:
            rows=db.execute("""SELECT e.account_id,e.broker_order_id,f.price,f.filled_at
                FROM autotrader_v3_execution_events e
                JOIN pg_live_mirror_verified_fill_v1 f ON f.account_id=e.account_id
                AND f.uic=e.uic AND f.asset_type=e.asset_type AND f.broker_order_id=e.broker_order_id
                WHERE e.instance_id=? AND e.uic=4912 AND e.asset_type='CfdOnIndex'
                AND e.executed_at>=? AND e.executed_at<=? LIMIT 4001""",
                (str(trader_id),utc(start).isoformat(),utc(end).isoformat())).fetchall()
        if len(rows)>4000:raise ValueError("fill limit")
        fills={(str(r["account_id"]),str(r["broker_order_id"])):dict(r) for r in rows}
    except Exception:
        pass
    return tuple(dict(r) for r in signals),attach_archived_fills(executions,fills),dict(state) if state else None

def attach_archived_fills(executions,fills):
    out=[]
    for row in executions:
        event=dict(row)
        f=(fills or {}).get((str(event["account_id"]),str(event["broker_order_id"])))
        event["fill_price"]=f["price"] if f else None
        event["filled_at"]=f["filled_at"] if f else None
        event["fill_evidence"]="SAXO_FINAL_FILL" if f else "ARCHIVE_UNAVAILABLE" if fills is None else "NOT_VERIFIED"
        # Internal identifiers are used only to join the records.
        event.pop("account_id",None)
        event.pop("broker_order_id",None)
        out.append(event)
    return tuple(out)

def compare_signals(trace,signals):
    expected={(utc(r["at"]),r["decision"]):r for r in trace if r.get("decision")}
    observed={(utc(r["quote_at"]),r["action"]):r for r in signals}
    counts=Counter(k[1] for k in expected)
    actual=Counter(k[1] for k in observed)
    rows=[dict(signal=reason,preview=counts[reason],worker=actual[reason],
               exact_matches=sum(k[1]==reason for k in expected.keys() & observed.keys()))
          for reason in sorted(counts.keys() | actual.keys())]
    events=[]
    for t,reason in sorted(expected.keys() | observed.keys()):
        k=(t,reason)
        events.append(dict(at=t,reason=reason,preview=k in expected,worker=k in observed,
                           preview_mid=expected[k]["mid"] if k in expected else None,
                           worker_mid=observed[k]["source_mid"] if k in observed else None))
    return rows,events
