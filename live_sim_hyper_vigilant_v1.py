"""Hyper-Vigilant Stochastic: strictly causal, quote-driven PAPER experiment.

No broker access, no LIVE configs, no positions, no mutable live trading path.
Stochastic direction leads; near-flat stochastic may defer to MACD; a confirmed
adverse price move flattens. Six simultaneous matched, forward-only arms
isolate MACD, price guard and three whipsaw responses.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone, timedelta
from statistics import median

from database import connect
from live_sim_hyper_quotes_v1 import _utc, ensure_hyper_quote_schema

RESEARCH_VERSION="hyper-stoch-1s-v1"
ARMS=("STOCH_ONLY","STOCH_MACD","STOCH_PRICE",
      "WHIP_PAUSE","WHIP_REDUCE","WHIP_FLAT")
INITIAL_EQUITY=10000.0
FEE_BPS=2.0
MAX_TICKS_PER_CYCLE=240
WARM_SAMPLES=45
MIN_HOLD_SECONDS=8
POST_EXIT_COOLDOWN_SECONDS=8
PRICE_GUARD_COOLDOWN_SECONDS=12
WHIP_FLAT_RELEASE_BUCKETS=3
_READY_SCHEMAS=set()


def ensure_hyper_schema(db):
    ensure_hyper_quote_schema(db)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS lsim_hyper_features(
            provider_uic INTEGER PRIMARY KEY,market_name TEXT NOT NULL,
            last_quote_at TEXT NOT NULL,state_json TEXT NOT NULL,
            started_at TEXT NOT NULL,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS lsim_hyper_tracks(
            provider_uic INTEGER NOT NULL,arm TEXT NOT NULL,
            state_json TEXT NOT NULL,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(provider_uic,arm)
        );
        CREATE TABLE IF NOT EXISTS lsim_hyper_points(
            provider_uic INTEGER NOT NULL,arm TEXT NOT NULL,quote_at TEXT NOT NULL,
            equity REAL NOT NULL,exposure REAL NOT NULL,decision TEXT NOT NULL,
            traded INTEGER NOT NULL,stoch_k REAL,stoch_d REAL,
            macd_hist REAL,whipsaw INTEGER NOT NULL,price_guard INTEGER NOT NULL,
            PRIMARY KEY(provider_uic,arm,quote_at)
        );
    """)


def _features():
    return {"last_quote":None,"samples":[],"buckets5":[],
            "ema20":None,"ema45":None,"macd_signal":None,"macd_hist":0.0,
            "k":None,"d":None,"k_delta":0.0,
            "whipsaw_raw":False,"whipsaw_active":False,
            "whipsaw_clear_buckets":0,"whipsaw_count":0,
            "quote_gap_count":0}


def _track():
    return {"equity":INITIAL_EQUITY,"peak":INITIAL_EQUITY,
            "max_drawdown":0.0,"exposure":0.0,"pending":0.0,
            "last_mid":None,"entry_mid":None,"last_quote":None,
            "last_trade":None,"cooldown_until":None,"ticks":0,"trades":0,
            "fees_nok":0.0,"spread_cost_nok":0.0,"price_guards":0,
            "whipsaw_bars":0,"whipsaw_blocks":0,"whipsaw_reductions":0,
            "whipsaw_flats":0,"stoch_decisions":0,"macd_fallbacks":0,
            "stale_ticks":0,"last_reason":"WARMUP"}


def _ema(previous,price,span):
    return float(price) if previous is None else float(previous)+(2/(span+1))*(float(price)-float(previous))


def _sample_feature(feature,*,at,mid):
    """Incrementally evaluate ONE actually observed, timestamped market sample."""
    f=dict(feature)
    stamp=_utc(at)
    stamp_str=stamp.isoformat()
    prev_time=f.get("last_quote")
    if prev_time is not None and stamp<=_utc(prev_time):
        return f
    recent=[[str(x[0]),float(x[1])] for x in f.get("samples",[])
            if (stamp-_utc(x[0])).total_seconds()<=180]
    previous_mid=recent[-1][1] if recent else None
    if prev_time and (stamp-_utc(prev_time)).total_seconds()>5:
        f["quote_gap_count"]=int(f.get("quote_gap_count",0))+1
        # A disconnected price feed cannot substantiate intrabar indicators.
        recent=[]
        previous_mid=None
        f["buckets5"]=[]
        f["k"]=f["d"]=None
        f["ema20"]=f["ema45"]=f["macd_signal"]=None
        f["macd_hist"]=0.0
        f["whipsaw_active"]=False
        f["whipsaw_raw"]=False
        f["whipsaw_clear_buckets"]=0
    recent.append([stamp_str,float(mid)])
    f["samples"]=recent
    f["last_quote"]=stamp_str
    f["ema20"]=_ema(f.get("ema20"),mid,20)
    f["ema45"]=_ema(f.get("ema45"),mid,45)
    line=f["ema20"]-f["ema45"]
    f["macd_signal"]=_ema(f.get("macd_signal"),line,15)
    f["macd_hist"]=line-f["macd_signal"]
    lookback=[v for t,v in recent if (stamp-_utc(t)).total_seconds()<60]
    prior_k=f.get("k")
    if len(lookback)>=WARM_SAMPLES and max(lookback)-min(lookback)>1e-8:
        k=100*(mid-min(lookback))/(max(lookback)-min(lookback))
        d=_ema(f.get("d"),k,8)
        f["k"]=k
        f["d"]=d
        f["k_delta"]=0.0 if prior_k is None else k-float(prior_k)
    else:
        f["k"]=f["d"]=None
        f["k_delta"]=0.0

    bucket=int(stamp.timestamp())//5
    stored=[[int(b),float(p)] for b,p in f.get("buckets5",[]) if bucket-int(b)<=15]
    new_bucket=not stored or stored[-1][0]!=bucket
    if new_bucket:
        stored.append([bucket,float(mid)])
    else:
        stored[-1][1]=float(mid)
    f["buckets5"]=stored
    # The current 5-second bucket is still forming. Only its predecessor
    # and earlier observations can become actionable detector evidence.
    if new_bucket:
        closed=stored[:-1]
        if len(closed)>=13:
            returns=[b/a-1 for (_,a),(_,b) in zip(closed[-13:],closed[-12:])]
            flips=sum(a*b<0 for a,b in zip(returns,returns[1:]))
            er=abs(sum(returns))/max(1e-12,sum(abs(v) for v in returns))
            raw=flips>=7 and er<0.35
            f["whipsaw_raw"]=raw
            active=bool(f.get("whipsaw_active",False))
            if raw:
                if not active:
                    f["whipsaw_count"]=int(f.get("whipsaw_count",0))+1
                f["whipsaw_active"]=True
                f["whipsaw_clear_buckets"]=0
            elif active:
                quiet=int(f.get("whipsaw_clear_buckets",0))+1
                f["whipsaw_clear_buckets"]=quiet
                if quiet>=WHIP_FLAT_RELEASE_BUCKETS:
                    f["whipsaw_active"]=False
            else:
                f["whipsaw_clear_buckets"]=0
        else:
            f["whipsaw_raw"]=False
    return f


def signal_from_features(feature,*,use_macd=True):
    """Follow Stochastic K direction first; consult MACD only when it is flat."""
    if feature.get("k") is None or feature.get("d") is None:
        return 0,"WARMUP",False
    delta=float(feature["k_delta"])
    kd=float(feature["k"])-float(feature["d"])
    # K slope is primary; K-D smooths its direction confirmation.
    if delta>=2.0 and kd>=1.0:
        return 1,"STOCH_UP",False
    if delta<=-2.0 and kd<=-1.0:
        return -1,"STOCH_DOWN",False
    if abs(delta)<=1.0 and abs(kd)<=3.0 and use_macd:
        prices=[v for _,v in feature.get("samples",[])[-45:]]
        noise=median([abs(y-x) for x,y in zip(prices,prices[1:])]) if len(prices)>2 else 0
        hist=float(feature.get("macd_hist",0))
        # Nonzero, noise-relative MACD fallback only in a near-flat Stoch state.
        if abs(hist)>max(0.02,3.0*noise):
            return (1 if hist>0 else -1),"MACD_FALLBACK",True
    return 0,"STOCH_NEUTRAL",False


def adverse_price_guard(feature,*,position,entry_mid,mid):
    """Conservative 15s price override independent of indicator orientation."""
    direction=1 if position>0 else -1 if position<0 else 0
    if not direction:
        return False,0.0
    stamp=_utc(feature["last_quote"])
    samples=[(t,float(p)) for t,p in feature["samples"]
             if (stamp-_utc(t)).total_seconds()<=16]
    earlier=next((p for t,p in samples
                  if 12<=(stamp-_utc(t)).total_seconds()<=16),None)
    if earlier is None or len(samples)<10:
        return False,0.0
    moves=[abs(b/a-1) for (_,a),(_,b) in zip(samples,samples[1:])]
    # Floor 0.06% (~18 index points at 30k) before overriding an oscillator.
    dynamic=max(0.0006,3.0*median(moves)*math.sqrt(15))
    move=mid/earlier-1
    entry_move=(mid/entry_mid-1) if entry_mid and entry_mid>0 else 0.0
    return (direction*move < -dynamic or
            direction*entry_move < -0.0012),dynamic


def policy_target(*,arm,signal,actual,whipsaw,price_adverse,
                  now,last_trade=None,cooldown_until=None):
    """Return next quote's target; no instant opposite-side reversal."""
    ts=_utc(now)
    current=float(actual)
    if price_adverse and arm!="STOCH_ONLY" and arm!="STOCH_MACD":
        return 0.0,"PRICE_GUARD_FLAT",PRICE_GUARD_COOLDOWN_SECONDS
    if arm.startswith("WHIP_") and whipsaw:
        if arm=="WHIP_FLAT":
            return 0.0,"WHIPSAW_FLAT",POST_EXIT_COOLDOWN_SECONDS
        if arm=="WHIP_REDUCE":
            return (math.copysign(0.5,current) if current else 0.0),"WHIPSAW_REDUCE",0
        if arm=="WHIP_PAUSE":
            if current and signal*current<0:
                return 0.0,"WHIPSAW_OPPOSITE_EXIT",POST_EXIT_COOLDOWN_SECONDS
            return current,"WHIPSAW_PAUSE",0
    if cooldown_until and ts<_utc(cooldown_until):
        return current,"COOLDOWN",0
    if signal==0:
        return current,"NEUTRAL_HOLD",0
    if current and current*signal<0:
        # Exit urgently; cannot open opposite exposure until later quote.
        return 0.0,"SIGNAL_FLAT_BEFORE_REVERSAL",POST_EXIT_COOLDOWN_SECONDS
    if current and last_trade and (ts-_utc(last_trade)).total_seconds()<MIN_HOLD_SECONDS:
        return current,"MIN_HOLD",0
    return float(signal),"STOCH_DIRECTION",0


def _settle_track(state,*,arm,feature,quote,trade_allowed):
    s=dict(state)
    stamp=_utc(quote["quote_at"])
    if s.get("last_quote") and stamp<=_utc(s["last_quote"]):
        return s,False
    bid,ask=float(quote["bid"]),float(quote["ask"])
    mid=(bid+ask)/2
    exposure=float(s.get("exposure",0))
    equity=float(s.get("equity",INITIAL_EQUITY))
    last_mid=s.get("last_mid")
    if last_mid and last_mid>0:
        equity*=1+exposure*(mid/float(last_mid)-1)
    trading=False
    # Fill PREVIOUS quote's intent on CURRENT observed bid/ask, not on the
    # signal quote itself. No fills against stale/down/unobserved timestamps.
    next_exposure=float(s.get("pending",0))
    if trade_allowed and abs(next_exposure-exposure)>1e-9:
        turnover=abs(next_exposure-exposure)
        spread_frac=(ask-bid)/(2*mid)
        spread_cost=equity*turnover*spread_frac
        commission=equity*turnover*FEE_BPS/10000
        equity-=spread_cost+commission
        s["fees_nok"]=float(s.get("fees_nok",0))+commission
        s["spread_cost_nok"]=float(s.get("spread_cost_nok",0))+spread_cost
        s["trades"]=int(s.get("trades",0))+1
        s["last_trade"]=stamp.isoformat()
        if next_exposure==0:
            s["entry_mid"]=None
        elif exposure==0 or next_exposure*exposure<0:
            s["entry_mid"]=mid
        exposure=next_exposure
        trading=True
    else:
        next_exposure=exposure
    s["pending"]=exposure
    s["exposure"]=exposure
    s["last_mid"]=mid
    s["last_quote"]=stamp.isoformat()
    s["ticks"]=int(s.get("ticks",0))+1
    peak=max(float(s.get("peak",INITIAL_EQUITY)),equity)
    s["equity"]=equity
    s["peak"]=peak
    s["max_drawdown"]=max(float(s.get("max_drawdown",0)),1-equity/max(peak,1e-9))
    if feature.get("whipsaw_active"):
        s["whipsaw_bars"]=int(s.get("whipsaw_bars",0))+1
    if not trade_allowed:
        s["stale_ticks"]=int(s.get("stale_ticks",0))+1
        s["last_reason"]="STALE_OR_GAPPED_QUOTE"
        return s,trading

    base_macd=arm!="STOCH_ONLY"
    signal,signal_reason,is_macd=signal_from_features(feature,use_macd=base_macd)
    if is_macd:
        s["macd_fallbacks"]=int(s.get("macd_fallbacks",0))+1
    if signal_reason.startswith("STOCH_") and signal:
        s["stoch_decisions"]=int(s.get("stoch_decisions",0))+1
    guard=False
    if arm not in ("STOCH_ONLY","STOCH_MACD"):
        guard,_=adverse_price_guard(feature,position=exposure,
                                    entry_mid=s.get("entry_mid"),mid=mid)
    target,policy,cooldown=policy_target(
        arm=arm,signal=signal,actual=exposure,
        whipsaw=bool(feature.get("whipsaw_active",False)),
        price_adverse=guard,now=stamp,last_trade=s.get("last_trade"),
        cooldown_until=s.get("cooldown_until"))
    if policy=="PRICE_GUARD_FLAT" and exposure:
        s["price_guards"]=int(s.get("price_guards",0))+1
    if policy=="WHIPSAW_PAUSE" and abs(signal)>0 and abs(exposure)<1:
        s["whipsaw_blocks"]=int(s.get("whipsaw_blocks",0))+1
    if policy=="WHIPSAW_REDUCE" and abs(target)<abs(exposure):
        s["whipsaw_reductions"]=int(s.get("whipsaw_reductions",0))+1
    if policy=="WHIPSAW_FLAT" and exposure:
        s["whipsaw_flats"]=int(s.get("whipsaw_flats",0))+1
    if cooldown and abs(target)<abs(exposure):
        s["cooldown_until"]=(stamp+timedelta(seconds=cooldown)).isoformat()
    s["pending"]=target
    s["last_reason"]=policy if policy not in ("STOCH_DIRECTION","NEUTRAL_HOLD") else signal_reason
    return s,trading


def process_hyper_cycle(*,db_path="pricegauger.db",now=None):
    """Consume truly new <=5s old provider-second quotes, persist six paper paths.

    On first startup, already-recorded quotes warm indicators only; NEVER
    backfill fictitious paper P/L. Duplicate quotes and restarts are idempotent.
    """
    path=str(db_path)
    if path not in _READY_SCHEMAS:
        with connect(path) as db:
            ensure_hyper_schema(db)
        _READY_SCHEMAS.add(path)
    moment=_utc(now or datetime.now(timezone.utc))
    count=0
    with connect(path) as db:
        # A concrete, subscribed Saxo Tech100 instrument with actual 1Hz data.
        feeds=db.execute("""
            SELECT DISTINCT q.provider_uic,q.market_name FROM lsim_hyper_quotes_1s q
            WHERE q.quote_at>=? AND q.quote_at<=? ORDER BY q.provider_uic LIMIT 2
        """,((moment-timedelta(minutes=5)).isoformat(),moment.isoformat())).fetchall()
        for feed in feeds:
            uic=int(feed["provider_uic"])
            row=db.execute(
                "SELECT state_json FROM lsim_hyper_features WHERE provider_uic=?",
                (uic,)).fetchone()
            if row is None:
                warm=db.execute("""
                    SELECT quote_at,bid,ask FROM lsim_hyper_quotes_1s
                    WHERE provider_uic=? AND quote_at<=?
                    ORDER BY quote_at DESC LIMIT 180
                """,(uic,moment.isoformat())).fetchall()
                features=_features()
                for quote in reversed(warm):
                    features=_sample_feature(
                        features,at=quote["quote_at"],
                        mid=(float(quote["bid"])+float(quote["ask"]))/2)
                # No artificial capital is booked for these bootstrap quotes.
                if not features["last_quote"]:
                    continue
                started=moment.isoformat()
                db.execute("""
                    INSERT INTO lsim_hyper_features(provider_uic,market_name,
                        last_quote_at,state_json,started_at) VALUES(?,?,?,?,?)
                    ON CONFLICT(provider_uic) DO NOTHING
                """,(uic,feed["market_name"],features["last_quote"],
                     json.dumps(features),started))
                for arm in ARMS:
                    db.execute("""
                        INSERT INTO lsim_hyper_tracks(provider_uic,arm,state_json)
                        VALUES(?,?,?) ON CONFLICT(provider_uic,arm) DO NOTHING
                    """,(uic,arm,json.dumps(_track())))
                continue
            features=json.loads(row["state_json"])
            tracks={}
            for track in db.execute("""
                SELECT arm,state_json FROM lsim_hyper_tracks WHERE provider_uic=?
            """,(uic,)).fetchall():
                tracks[track["arm"]]=json.loads(track["state_json"])
            for arm in ARMS:
                tracks.setdefault(arm,_track())
            ticks=db.execute("""
                SELECT quote_at,bid,ask FROM lsim_hyper_quotes_1s
                WHERE provider_uic=? AND quote_at>? AND quote_at<=?
                ORDER BY quote_at LIMIT ?
            """,(uic,features["last_quote"],moment.isoformat(),
                 MAX_TICKS_PER_CYCLE)).fetchall()
            for quote in ticks:
                stamp=_utc(quote["quote_at"])
                prev=_utc(features["last_quote"])
                gap=(stamp-prev).total_seconds()
                fresh=(moment-stamp).total_seconds()<=5 and 0<gap<=5
                mid=(float(quote["bid"])+float(quote["ask"]))/2
                features=_sample_feature(features,at=stamp,mid=mid)
                for arm in ARMS:
                    state,traded=_settle_track(
                        tracks[arm],arm=arm,feature=features,quote=quote,
                        trade_allowed=fresh)
                    tracks[arm]=state
                    if traded or int(stamp.timestamp())%5==0 or "GUARD" in state["last_reason"]:
                        db.execute("""
                            INSERT INTO lsim_hyper_points(
                                provider_uic,arm,quote_at,equity,exposure,decision,
                                traded,stoch_k,stoch_d,macd_hist,whipsaw,price_guard)
                            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                            ON CONFLICT(provider_uic,arm,quote_at) DO NOTHING
                        """,(uic,arm,stamp.isoformat(),state["equity"],
                             state["exposure"],state["last_reason"],int(traded),
                             features.get("k"),features.get("d"),
                             features.get("macd_hist"),
                             int(bool(features.get("whipsaw_active"))),
                             int(state["last_reason"]=="PRICE_GUARD_FLAT")))
                count+=1
            if ticks:
                db.execute("""
                    UPDATE lsim_hyper_features
                    SET last_quote_at=?,state_json=?,updated_at=CURRENT_TIMESTAMP
                    WHERE provider_uic=?
                """,(features["last_quote"],json.dumps(features),uic))
                for arm,state in tracks.items():
                    db.execute("""
                        INSERT INTO lsim_hyper_tracks(provider_uic,arm,state_json)
                        VALUES(?,?,?) ON CONFLICT(provider_uic,arm) DO UPDATE SET
                          state_json=excluded.state_json,updated_at=CURRENT_TIMESTAMP
                    """,(uic,arm,json.dumps(state)))
    return count


def hyper_snapshot(*,db_path="pricegauger.db"):
    path=str(db_path)
    with connect(path) as db:
        ensure_hyper_schema(db)
        streams=[dict(row) for row in db.execute("""
            SELECT provider_uic,market_name,last_quote_at,state_json,started_at
            FROM lsim_hyper_features ORDER BY provider_uic
        """).fetchall()]
        tracks=[dict(row) for row in db.execute("""
            SELECT provider_uic,arm,state_json FROM lsim_hyper_tracks
            ORDER BY provider_uic,arm
        """).fetchall()]
        points=[dict(row) for row in db.execute("""
            SELECT provider_uic,arm,quote_at,equity,exposure,decision,
                traded,stoch_k,stoch_d,macd_hist,whipsaw,price_guard
            FROM lsim_hyper_points ORDER BY quote_at DESC LIMIT 1800
        """).fetchall()]
    for row in streams:
        row.update(json.loads(row.pop("state_json")))
    for row in tracks:
        row.update(json.loads(row.pop("state_json")))
    return streams,tracks,list(reversed(points))
