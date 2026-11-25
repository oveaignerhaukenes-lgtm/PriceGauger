"""Bounded forward diagnostics for one exact mirror session.

Match by instance + completed bar, not nearest trade timestamp. Compare the
raw base target separately from realized inventory. No inferred LIVE fill
price, no assumption that an absent POST is a successful NO_CHANGE.
This diagnostic is not the frozen independent holdout acceptance report.
"""
from datetime import datetime,timedelta,timezone
from math import isfinite
import json
from database import connect,run_postgres_schema_once_v1
from live_mirror_registry_v1 import _stamp,_json


def _read(db_path,sql,args):
    with connect(db_path) as db:
        return [dict(r) for r in db.execute(sql,args).fetchall()]


def summarize_pairs(live,sim):
    """All union keys are denominators; unknown outcomes are never agreements."""
    keys=set(live)|set(sim)
    paired=set(live)&set(sim)
    target=inventory=outcome=known=0
    price_errors=[]; latency_errors=[]
    for k in paired:
        l,s=live[k],sim[k]
        if l.get("raw") is not None and s.get("raw") is not None:
            target+=int(abs(l["raw"]-s["raw"])<=1e-9)
        if l.get("outcome") in ("UNKNOWN","UNOBSERVED","PENDING") or s.get("outcome") in ("UNKNOWN","UNOBSERVED","PENDING"):
            continue
        known+=1
        outcome+=int(l["outcome"]==s["outcome"])
        if l.get("inventory_after") is not None and s.get("inventory_after") is not None:
            inventory+=int(abs(l["inventory_after"]-s["inventory_after"])<=1e-9)
        if l["outcome"]==s["outcome"]=="FILLED" and l.get("verified") and (
            l.get("side")==s.get("side") and l.get("amount") is not None
            and s.get("amount") is not None and abs(l["amount"]-s["amount"])<=1e-9
            and l.get("price") is not None and s.get("price") is not None
            and l.get("latency_s") is not None and s.get("latency_s") is not None):
            price_errors.append(abs(l["price"]-s["price"]))
            latency_errors.append(abs(l["latency_s"]-s["latency_s"]))
    n=len(keys)
    ratio=lambda x: x/n if n else None
    return dict(union=n,paired=len(paired),only_live=len(set(live)-set(sim)),
                only_sim=len(set(sim)-set(live)),known_pairs=known,
                coverage=ratio(len(paired)),target_agreement=ratio(target),
                inventory_agreement=ratio(inventory),outcome_agreement=ratio(outcome),
                verified_fill_pairs=len(price_errors),
                price_mae_points=sum(price_errors)/len(price_errors) if price_errors else None,
                latency_mae_s=sum(latency_errors)/len(latency_errors) if latency_errors else None,
                status="DIAGNOSTIC_ONLY",passed=False,pnl_validated=False)


def _live_rows(*,session,cfg,until,db_path):
    identity=session["instance_id"]
    start=_stamp(session["started_at"])
    key=cfg["strategy"]["strategy_key"]
    tf=cfg["strategy"]["timeframe"]
    minutes=int(tf[:-1])
    decisions=_read(db_path,"""SELECT decision_key,observed_at,payload_json
        FROM pg_live_mirror_trace_v1 WHERE instance_id=? AND event_type='DECISION'
        AND observed_at>=? AND observed_at<=? ORDER BY observed_at DESC LIMIT 1000""",
        (identity,start.isoformat(),until.isoformat()))
    # Scope exact request key and account boundary, not another instance's fill.
    subs=_read(db_path,"""SELECT t.decision_key,t.payload_json,g.state,g.detail,
            e.inventory_after,f.price,f.filled_at
        FROM pg_live_mirror_trace_v1 t
        LEFT JOIN autotrader_v3_order_guard g ON t.event_key=('submission:' || g.request_key)
          AND g.trader_id=t.instance_id
        LEFT JOIN autotrader_v3_execution_events e ON e.request_key=g.request_key
          AND e.instance_id=g.trader_id AND e.account_id=g.account_id AND e.uic=g.uic AND e.asset_type=g.asset_type
        LEFT JOIN pg_live_mirror_verified_fill_v1 f ON f.account_id=e.account_id
          AND f.uic=e.uic AND f.asset_type=e.asset_type AND f.broker_order_id=e.broker_order_id
        WHERE t.instance_id=? AND t.event_type='SUBMIT' AND t.observed_at>=?
          AND t.observed_at<=? ORDER BY t.observed_at DESC LIMIT 1000""",
        (identity,start.isoformat(),until.isoformat()))
    by_decision={}
    for row in subs:
        by_decision.setdefault(row["decision_key"],[]).append(row)
    regime_blocks=set()
    try:
        regime_blocks={r["decision_key"] for r in _read(db_path,"""SELECT decision_key
            FROM pg_v3_regime_block_event_v1 WHERE instance_id=? AND blocked_at>=? AND blocked_at<=?""",
            (identity,start.isoformat(),until.isoformat()))}
    except Exception:
        pass
    output={}
    for r in decisions:
        p=json.loads(r["payload_json"])
        if p.get("strategy")!=key or p.get("timeframe")!=tf:
            continue
        prefix,sep,bar=r["decision_key"].rpartition("|")
        opened=_stamp(bar)
        if not sep or prefix!=identity or not opened:
            continue
        closed=opened+timedelta(minutes=minutes)
        decided=_stamp(r["observed_at"])
        if closed<=start or closed>until or decided<closed:
            continue
        b=closed.isoformat()
        live=dict(raw=p.get("raw"),inventory_after=None,outcome="UNOBSERVED")
        items=by_decision.get(r["decision_key"],[])
        if len(items)==1:
            item=items[0];post=json.loads(item["payload_json"])
            state=item.get("state")
            if state=="RECONCILED" and item.get("inventory_after") is not None:
                live.update(outcome="FILLED",inventory_after=float(item["inventory_after"]))
                at=_stamp(item.get("filled_at"))
                if at and at>=decided and item.get("price") is not None:
                    live.update(verified=True,price=float(item["price"]),
                                latency_s=(at-decided).total_seconds(),
                                side=str(post["side"]).upper(),amount=float(post["amount"]))
            elif state=="REJECTED":
                detail=str(item.get("detail") or "").lower()
                status="MARGIN_REJECTED" if "margin" in detail else "RATE_LIMITED" if "ratelimit" in detail or "http 429" in detail else "REJECTED"
                live.update(outcome=status,inventory_after=post.get("actual"))
        elif not items and ((p.get("approved")==p.get("actual") and p.get("actual") is not None) or r["decision_key"] in regime_blocks):
            live.update(outcome="NO_CHANGE",inventory_after=p.get("actual"))
        if b in output:
            # Ambiguous duplicate or switched context never silently matched.
            output[b]={"raw":None,"outcome":"UNOBSERVED","inventory_after":None}
        else:
            output[b]=live
    return output


def _sim_rows(*,session,until,db_path):
    rows=_read(db_path,"""SELECT decision_bar,decided_at,outcome,event_json
        FROM pg_live_mirror_event_v1 WHERE session_id=? AND decided_at<=?
        ORDER BY decided_at DESC LIMIT 1000""",(session["session_id"],until.isoformat()))
    out={}
    for r in rows:
        p=json.loads(r["event_json"])
        value=dict(raw=p.get("raw"),outcome=r["outcome"],inventory_after=p.get("inventory_after"))
        if r["outcome"]=="FILLED":
            before=p.get("inventory_before");after=p.get("inventory_after")
            at=_stamp(p.get("fill_received_at"));decided=_stamp(r["decided_at"])
            if before is not None and after is not None and at and decided:
                delta=after-before
                value.update(side="BUY" if delta>0 else "SELL",amount=abs(delta),
                             price=p.get("price"),latency_s=(at-decided).total_seconds())
        out[_stamp(r["decision_bar"]).isoformat()]=value
    return out


def refresh_comparisons(*,db_path="pricegauger.db",now=None):
    """Write only diagnostic reports; no automatic pass or live promotion."""
    from live_mirror_execution_v1 import execution_snapshot
    from live_mirror_registry_v1 import mirror_snapshot
    from live_mirror_audit_v1 import ensure_audit_schema
    now=now or datetime.now(timezone.utc)
    refs={r["mirror_id"]:r for r in (mirror_snapshot(db_path=db_path) or ())}
    sessions=execution_snapshot(db_path=db_path) or ()
    if not sessions:
        return 0
    ensure_audit_schema(db_path)
    def initialize():
        with connect(db_path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS pg_live_mirror_comparison_v1(
                session_id TEXT PRIMARY KEY,observed_at TEXT NOT NULL,report_json TEXT NOT NULL)""")
    run_postgres_schema_once_v1("pg_live_mirror_comparison_v1",initialize)
    done=0
    until=now-timedelta(seconds=30)
    for session in sessions:
        try:
            row=refs[session["mirror_id"]]
            cfg=json.loads(row["config_json"])
            live=_live_rows(session=session,cfg=cfg,until=until,db_path=db_path)
            sim=_sim_rows(session=session,until=until,db_path=db_path)
            report=summarize_pairs(live,sim)
        except Exception:
            report={"status":"EVIDENCE_UNAVAILABLE","passed":False,"pnl_validated":False}
        with connect(db_path) as db:
            db.execute("""INSERT INTO pg_live_mirror_comparison_v1(session_id,observed_at,report_json)
                VALUES(?,?,?) ON CONFLICT(session_id) DO UPDATE SET
                observed_at=excluded.observed_at,report_json=excluded.report_json""",
                (session["session_id"],now.isoformat(),_json(report)))
        done+=1
    return done


def comparison_snapshot(*,db_path="pricegauger.db"):
    try:
        return {r["session_id"]:json.loads(r["report_json"]) for r in _read(db_path,
                 "SELECT session_id,report_json FROM pg_live_mirror_comparison_v1",())}
    except Exception:
        return {}
