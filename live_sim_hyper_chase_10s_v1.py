"""HyperVigilant Chase 10s — forward-only Saxo quote PAPER experiment.

Price-first, no MACD wait and no deliberate flat/cooldown. A DIRECT
LONG(+1)->SHORT(-1) flip fills on the next fresh observed quote, NEVER on
the signal quote. Both exit and entry pay spread, commission, slippage.
This experiment has NO broker client, Saxo orders or LIVE authorization.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from statistics import median

from database import connect
from live_sim_hyper_quotes_v1 import _utc, ensure_hyper_quote_schema

ARMS=("CHASE_10S_FAST","CHASE_10S_FILTERED")
VERSION="hyper-chase-10s-direct-flip-paper-v1"
INITIAL_EQUITY=10000.
LOOKBACK_SECONDS=10
MIN_SIGNAL_HISTORY=9
MAX_FEED_GAP_SECONDS=3
MAX_QUOTE_AGE_SECONDS=5
MAX_TICKS_PER_CYCLE=150
FEE_BPS_PER_SIDE=2.
SLIPPAGE_BPS_PER_SIDE=1.
FAST_MOVE_BPS=4.5
FILTERED_MOVE_BPS=8.
MAX_SPREAD_BPS=6.
_REVIEWED_SCHEMAS=set()


def ensure_chase_schema(db):
    ensure_hyper_quote_schema(db)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS lsim_hyper_chase_tracks (
            provider_uic INTEGER NOT NULL, arm TEXT NOT NULL,
            market_name TEXT NOT NULL, started_at TEXT NOT NULL,
            state_json TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(provider_uic,arm)
        );
        CREATE TABLE IF NOT EXISTS lsim_hyper_chase_points (
            provider_uic INTEGER NOT NULL, arm TEXT NOT NULL,
            quote_at TEXT NOT NULL, mid REAL NOT NULL, spread_bps REAL NOT NULL,
            equity REAL NOT NULL, exposure REAL NOT NULL, signal INTEGER NOT NULL,
            action TEXT NOT NULL, traded INTEGER NOT NULL, turnover REAL NOT NULL,
            signal_delay_seconds REAL, total_cost_nok REAL NOT NULL,
            evidence_json TEXT NOT NULL,
            PRIMARY KEY(provider_uic,arm,quote_at)
        );
        CREATE INDEX IF NOT EXISTS lsim_chase_points_time
        ON lsim_hyper_chase_points(quote_at);
    """)


def _track(at,mid):
    return {
        "version":VERSION,"equity":INITIAL_EQUITY,"peak":INITIAL_EQUITY,
        "max_drawdown":0.,"exposure":0.,"pending":None,"pending_at":None,
        "last_quote":_utc(at).isoformat(),"last_mid":float(mid),
        "samples":[[_utc(at).isoformat(),float(mid)]],
        "ticks":0,"trades":0,"flips":0,"entries":0,
        "fees_nok":0.,"spread_cost_nok":0.,"slippage_nok":0.,
        "last_reason":"PROSPECTIVE_WARMUP","last_signal":0,
        "last_signal_at":None,"last_fill_delay_seconds":None,
        "gaps":0,"stale_quotes":0,"blocked_spread":0,
        "fresh_signal_count":0,
    }


def chase_signal_v1(samples,*,at,bid,ask,arm):
    """Only 1s observations already received as-of at; no interpolation."""
    now=_utc(at)
    if arm not in ARMS:raise ValueError("unknown chase arm")
    try:
        bid=float(bid);ask=float(ask)
    except (TypeError,ValueError):
        return 0,"BAD_BBO",{}
    if not all(math.isfinite(x) and x>0 for x in (bid,ask)) or ask<bid:
        return 0,"BAD_BBO",{}
    mid=(bid+ask)/2
    spread_bps=10000*(ask-bid)/mid
    if spread_bps>MAX_SPREAD_BPS:
        return 0,"WIDE_SPREAD",{"spread_bps":round(spread_bps,3)}
    recent=[]
    for t,p in samples:
        stamp=_utc(t)
        seconds=(now-stamp).total_seconds()
        if 0<=seconds<=LOOKBACK_SECONDS:
            recent.append((stamp,float(p)))
    recent.sort(key=lambda x:x[0])
    if len(recent)<MIN_SIGNAL_HISTORY:
        return 0,"NEED_FRESH_QUOTES",{"samples":len(recent)}
    # Require an actual observed quote 9-10 seconds ago; otherwise
    # the 10s momentum is unknown, not a synthetic interpolation.
    old=[(when,p) for when,p in recent if 9<=(now-when).total_seconds()<=10]
    if not old:return 0,"NO_10S_REFERENCE",{"samples":len(recent)}
    for (a,_),(b,_) in zip(recent,recent[1:]):
        if not 0<(b-a).total_seconds()<=MAX_FEED_GAP_SECONDS:
            return 0,"GAPPED_1S",{}
    prior=old[0][1]
    if not prior>0:return 0,"BAD_REFERENCE",{}
    move_bps=10000*(mid/prior-1)
    returns=[10000*abs(b/a-1) for (_,a),(_,b) in zip(recent,recent[1:])]
    noise=median(returns) if returns else 0.
    # Chasing below round-trip friction is likely negative expectancy.
    min_cost=2*(spread_bps+FEE_BPS_PER_SIDE+SLIPPAGE_BPS_PER_SIDE)
    threshold=max(
        FAST_MOVE_BPS if arm==ARMS[0] else FILTERED_MOVE_BPS,
        2.5*noise if arm==ARMS[0] else 4.0*noise,
        min_cost,
    )
    evidence={
        "at":now.isoformat(),"lookback_seconds":LOOKBACK_SECONDS,
        "observations":len(recent),"move_10s_bps":round(move_bps,3),
        "spread_bps":round(spread_bps,3),
        "median_abs_quote_move_bps":round(noise,3),
        "threshold_bps":round(threshold,3),
    }
    if abs(move_bps)<threshold:
        return 0,"BELOW_THRESHOLD",evidence
    direction=1 if move_bps>0 else -1
    if arm==ARMS[1]:
        # Slower control demands directional consistency across two
        # independent subwindows; still NO waiting for closed 1m bars.
        midpoint=next((p for t,p in recent
                       if 4<=(now-t).total_seconds()<=6),None)
        if midpoint is None or (
            direction*(mid/midpoint-1)<=0 or
            direction*(midpoint/prior-1)<=0
        ):
            return 0,"SPLIT_WINDOW_CONFLICT",evidence
    return direction,"CHASE_10S_IMPULSE",evidence


def settle_chase_quote_v1(state,*,arm,quote,now):
    """Mark previous position, fill prior signal, then compute new signal."""
    t=_utc(quote["quote_at"]); clock=_utc(now)
    prior=_utc(state["last_quote"])
    if t<=prior:
        return dict(state),None
    s=dict(state)
    bid=float(quote["bid"]);ask=float(quote["ask"])
    if not (math.isfinite(bid) and math.isfinite(ask)
            and 0<bid<=ask):
        return s,None
    mid=(bid+ask)/2
    gap=(t-prior).total_seconds()
    age=(clock-t).total_seconds()
    fresh=0<=age<=MAX_QUOTE_AGE_SECONDS and 0<gap<=MAX_FEED_GAP_SECONDS
    current=float(s["exposure"])
    equity=float(s["equity"])
    prev_mid=float(s["last_mid"])
    # Mark existing position to *actually observed* new midpoint.
    # After a gap this includes an unobserved interval; flag its quality.
    equity*=1+current*(mid/prev_mid-1)
    spent=0.;turnover=0.;traded=False;action="HOLD"
    if not fresh:
        s["gaps"]=int(s["gaps"])+(gap>MAX_FEED_GAP_SECONDS)
        s["stale_quotes"]=int(s["stale_quotes"])+(age>MAX_QUOTE_AGE_SECONDS or age<0)
        s["pending"]=None;s["pending_at"]=None
        s["samples"]=[]
        action="FEED_GAP_NO_TRADE" if gap>MAX_FEED_GAP_SECONDS else "STALE_QUOTE_NO_TRADE"
        signal=0;evidence={"gap_seconds":gap,"quote_age_seconds":age,
                          "unobserved_gap_marked":gap>MAX_FEED_GAP_SECONDS}
    else:
        pending=s.get("pending")
        when=s.get("pending_at")
        if pending is not None and when and t>_utc(when):
            wanted=float(pending)
            # DIRECT +1 -> -1 at this NEXT observed quote; two tradable
            # legs with 2 units turnover, not a cost-free magic netting.
            turnover=abs(wanted-current)
            if turnover>0:
                spread_cost=equity*turnover*(ask-bid)/(2*mid)
                commission=equity*turnover*FEE_BPS_PER_SIDE/10000
                slippage=equity*turnover*SLIPPAGE_BPS_PER_SIDE/10000
                spent=spread_cost+commission+slippage
                equity-=spent
                s["spread_cost_nok"]+=spread_cost
                s["fees_nok"]+=commission
                s["slippage_nok"]+=slippage
                s["trades"]+=1
                if current*wanted<0:s["flips"]+=1;action="DIRECT_FLIP"
                elif not current:s["entries"]+=1;action="OPEN"
                elif not wanted:action="FLAT"
                else:action="POSITION_CHANGE"
                current=wanted
                traded=True
        s["pending"]=None;s["pending_at"]=None
        samples=[
            (stamp,float(p)) for stamp,p in s.get("samples",[])
            if 0<=(t-_utc(stamp)).total_seconds()<=LOOKBACK_SECONDS
        ]
        samples.append((t.isoformat(),mid))
        s["samples"]=samples[-16:]
        signal,reason,evidence=chase_signal_v1(
            s["samples"],at=t,bid=bid,ask=ask,arm=arm)
        if reason=="WIDE_SPREAD":s["blocked_spread"]+=1
        if signal:
            s["fresh_signal_count"]+=1
            s["last_signal"]=signal
            s["last_signal_at"]=t.isoformat()
            if signal!=current:
                s["pending"]=float(signal)
                s["pending_at"]=t.isoformat()
                if not traded:action="CHASE_10S_SIGNAL"
        s["last_reason"]=reason
        if traded and when:
            s["last_fill_delay_seconds"]=(t-_utc(when)).total_seconds()
    s["equity"]=equity
    s["exposure"]=current
    s["peak"]=max(float(s["peak"]),equity)
    s["max_drawdown"]=max(float(s["max_drawdown"]),
                          1-equity/max(float(s["peak"]),1e-9))
    s["last_quote"]=t.isoformat()
    s["last_mid"]=mid
    s["ticks"]+=1
    if not fresh:s["last_reason"]=action
    event={
        "quote_at":t.isoformat(),"mid":mid,
        "spread_bps":10000*(ask-bid)/mid,
        "equity":equity,"exposure":current,"signal":signal,
        "action":action,"traded":int(traded),"turnover":turnover,
        "signal_delay_seconds":s.get("last_fill_delay_seconds") if traded else None,
        "total_cost_nok":spent,"evidence":evidence,
    }
    return s,event


def process_chase_cycle_v1(*,db_path="pricegauger.db",now=None):
    """Prospective-only 1s quote follower; never backtest old ticks as fills."""
    clock=_utc(now or datetime.now(timezone.utc))
    path=str(db_path)
    if path not in _REVIEWED_SCHEMAS:
        with connect(path) as db:ensure_chase_schema(db)
        _REVIEWED_SCHEMAS.add(path)
    processed=0
    with connect(path) as db:
        feeds=db.execute("""
            SELECT provider_uic,market_name,MAX(quote_at) AS last_quote
            FROM lsim_hyper_quotes_1s WHERE quote_at>=? AND quote_at<=?
            GROUP BY provider_uic,market_name
            ORDER BY provider_uic LIMIT 2
        """,((clock-timedelta(minutes=2)).isoformat(),clock.isoformat())).fetchall()
        for feed in feeds:
            uic=int(feed["provider_uic"])
            rows=db.execute("""
                SELECT arm,state_json FROM lsim_hyper_chase_tracks
                WHERE provider_uic=?
            """,(uic,)).fetchall()
            tracks={r["arm"]:json.loads(r["state_json"]) for r in rows}
            if any(arm not in tracks for arm in ARMS):
                last=db.execute("""
                    SELECT quote_at,bid,ask FROM lsim_hyper_quotes_1s
                    WHERE provider_uic=? AND quote_at<=?
                    ORDER BY quote_at DESC LIMIT 1
                """,(uic,clock.isoformat())).fetchone()
                if last is None:continue
                mid=(float(last["bid"])+float(last["ask"]))/2
                # No retrospective trades at boot, even if historical
                # signals were unambiguous in stored quotes.
                for arm in ARMS:
                    if arm not in tracks:
                        state=_track(last["quote_at"],mid)
                        db.execute("""
                            INSERT INTO lsim_hyper_chase_tracks(
                                provider_uic,arm,market_name,started_at,state_json)
                            VALUES(?,?,?,?,?) ON CONFLICT(provider_uic,arm) DO NOTHING
                        """,(uic,arm,feed["market_name"],clock.isoformat(),
                             json.dumps(state)))
                continue
            # Both arms consume identical genuine quote timestamps.
            since=min(_utc(tracks[arm]["last_quote"]) for arm in ARMS)
            quotes=db.execute("""
                SELECT quote_at,bid,ask FROM lsim_hyper_quotes_1s
                WHERE provider_uic=? AND quote_at>? AND quote_at<=?
                ORDER BY quote_at LIMIT ?
            """,(uic,since.isoformat(),clock.isoformat(),
                 MAX_TICKS_PER_CYCLE)).fetchall()
            if not quotes:continue
            for q in quotes:
                for arm in ARMS:
                    state=tracks[arm]
                    updated,event=settle_chase_quote_v1(
                        state,arm=arm,quote=q,now=clock)
                    tracks[arm]=updated
                    if event is None:continue
                    if event["traded"] or (
                        _utc(q["quote_at"]).second%5==0
                    ) or event["action"]=="CHASE_10S_SIGNAL":
                        db.execute("""
                            INSERT INTO lsim_hyper_chase_points(
                                provider_uic,arm,quote_at,mid,spread_bps,
                                equity,exposure,signal,action,traded,turnover,
                                signal_delay_seconds,total_cost_nok,evidence_json)
                            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                            ON CONFLICT(provider_uic,arm,quote_at) DO NOTHING
                        """,(
                            uic,arm,event["quote_at"],event["mid"],
                            event["spread_bps"],event["equity"],
                            event["exposure"],event["signal"],event["action"],
                            event["traded"],event["turnover"],
                            event["signal_delay_seconds"],
                            event["total_cost_nok"],
                            json.dumps(event["evidence"],allow_nan=False),
                        ))
                processed+=1
            for arm,state in tracks.items():
                db.execute("""
                    UPDATE lsim_hyper_chase_tracks
                    SET state_json=?,updated_at=CURRENT_TIMESTAMP
                    WHERE provider_uic=? AND arm=?
                """,(json.dumps(state,allow_nan=False),uic,arm))
    return processed


def chase_snapshot_v1(*,db_path="pricegauger.db",limit=1400):
    with connect(db_path) as db:
        ensure_chase_schema(db)
        tracks=[dict(row) for row in db.execute("""
            SELECT provider_uic,arm,market_name,started_at,state_json
            FROM lsim_hyper_chase_tracks ORDER BY provider_uic,arm
        """).fetchall()]
        points=[dict(row) for row in db.execute("""
            SELECT provider_uic,arm,quote_at,mid,spread_bps,
                equity,exposure,signal,action,traded,turnover,
                signal_delay_seconds,total_cost_nok,evidence_json
            FROM lsim_hyper_chase_points ORDER BY quote_at DESC LIMIT ?
        """,(max(1,min(4000,int(limit))),)).fetchall()]
    for r in tracks:r.update(json.loads(r.pop("state_json")))
    for r in points:r["evidence"]=json.loads(r.pop("evidence_json"))
    return tracks,list(reversed(points))


__all__=[
    "ARMS","VERSION","chase_signal_v1",
    "settle_chase_quote_v1","process_chase_cycle_v1",
    "chase_snapshot_v1","ensure_chase_schema",
]
