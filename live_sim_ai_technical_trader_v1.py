"""AI Trader v1 – technical-only, event-driven, independent PAPER portfolio.

No broker imports, Saxo order endpoints, account permissions or LIVE config.
The AI can propose both new positions and risk reductions; a deterministic
risk gate bounds every proposal. Quotes are marked and fills occur on NEXT
actually observed bid/ask, never retroactively at the signal quote.

All LLM input contains numerical technical and PAPER exposure data only.
No news, macroeconomic or geopolitical context enters the request.
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median

import requests

from database import connect
from live_sim_hyper_quotes_v1 import _utc, ensure_hyper_quote_schema

MODEL_DEFAULT="gpt-5-mini"
RESPONSES_URL="https://api.openai.com/v1/responses"
VERSION="ai-technical-paper-v1"
ARM="AI_TECH"
START_EQUITY=10000.0
FEE_BPS=2.0
MAX_EXPOSURE=1.0
MAX_STEP=0.5
PAPER_COST_FLOOR=0.0006
LOSS_SECONDS=60
DECISION_COOLDOWN_SECONDS=90
ROUTINE_INTERVAL_SECONDS=180
MAX_DAILY_CALLS=80
MAX_REQUEST_AGE_SECONDS=12
MAX_QUOTE_AGE_SECONDS=5
MAX_QUOTE_GAP_SECONDS=5
MAX_QUOTES_PER_CYCLE=240


def ensure_ai_schema(db):
    ensure_hyper_quote_schema(db)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS lsim_ai_technical_accounts(
            provider_uic INTEGER PRIMARY KEY,market_name TEXT NOT NULL,
            state_json TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS lsim_ai_technical_decisions(
            provider_uic INTEGER NOT NULL,as_of TEXT NOT NULL,
            event_kind TEXT NOT NULL,requested_at TEXT NOT NULL,
            model TEXT NOT NULL,model_status TEXT NOT NULL,
            target REAL,confidence REAL,reason TEXT NOT NULL,
            gate_reason TEXT NOT NULL,evidence_json TEXT NOT NULL,
            PRIMARY KEY(provider_uic,as_of)
        );
        CREATE TABLE IF NOT EXISTS lsim_ai_technical_points(
            provider_uic INTEGER NOT NULL,quote_at TEXT NOT NULL,
            equity REAL NOT NULL,exposure REAL NOT NULL,
            traded INTEGER NOT NULL,decision TEXT NOT NULL,
            PRIMARY KEY(provider_uic,quote_at)
        );
        CREATE INDEX IF NOT EXISTS lsim_ai_technical_decisions_by_date
            ON lsim_ai_technical_decisions(requested_at);
    """)


def _initial_state(*,quote_time,mid,baseline_nav):
    return {
        "version":VERSION,"started_at":str(quote_time),
        "equity":START_EQUITY,"peak":START_EQUITY,"max_drawdown":0.0,
        "paired_baseline_equity":baseline_nav,
        "exposure":0.0,"pending":0.0,"pending_as_of":None,
        "entry_mid":None,"last_mid":float(mid),"last_quote":str(quote_time),
        "last_evaluated_at":None,"negative_since":None,
        "last_trade":None,"ticks":0,"trades":0,"fees_nok":0.0,
        "spread_cost_nok":0.0,"data_gaps":0,"rejected_requests":0,
        "ai_calls":0,"accepted_decisions":0,"loss_triggers":0,
        "last_reason":"WAIT_AI","last_model_status":"NO_CALL",
    }


def _fresh_second(at,*,now):
    time=_utc(at)
    seconds=(_utc(now)-time).total_seconds()
    return 0<=seconds<=MAX_QUOTE_AGE_SECONDS


def _mark_account(state,quote):
    """Settle one observed quote; stage an earlier decision until next quote.

    Signals created at quote_at T cannot change exposure during T's price
    movement. On a disconnection, pending unfilled intents are invalidated.
    """
    updated=dict(state)
    stamp=_utc(quote["quote_at"])
    if stamp<=_utc(updated["last_quote"]):
        return updated,False
    bid,ask=float(quote["bid"]),float(quote["ask"])
    mid=(bid+ask)/2
    old_mid=float(updated["last_mid"])
    before=float(updated["exposure"])
    equity=float(updated["equity"])
    equity*=1+before*(mid/old_mid-1)
    gap=(stamp-_utc(updated["last_quote"])).total_seconds()
    traded=False
    allowed=gap<=MAX_QUOTE_GAP_SECONDS
    target=float(updated.get("pending",before))
    planned_at=updated.get("pending_as_of")
    if not allowed:
        updated["data_gaps"]+=1
        target=before
        updated["pending"]=before
        updated["pending_as_of"]=None
        updated["negative_since"]=None
        updated["last_reason"]="FEED_GAP_NO_FILL"
    elif planned_at and stamp>_utc(planned_at) and abs(target-before)>1e-9:
        turnover=abs(target-before)
        spread_cost=equity*turnover*(ask-bid)/(2*mid)
        fee=equity*turnover*FEE_BPS/10000.0
        equity-=spread_cost+fee
        updated["spread_cost_nok"]+=spread_cost
        updated["fees_nok"]+=fee
        updated["trades"]+=1
        updated["last_trade"]=stamp.isoformat()
        if target==0:
            updated["entry_mid"]=None
        elif before==0 or target*before<0:
            updated["entry_mid"]=mid
        before=target
        traded=True
        updated["last_reason"]="AI_FILLED_NEXT_QUOTE"
        updated["pending_as_of"]=None
    # Set entry's marked price conservatively: never reset on reductions.
    updated["pending"]=before
    updated["exposure"]=before
    updated["equity"]=equity
    updated["peak"]=max(float(updated["peak"]),equity)
    updated["max_drawdown"]=max(
        float(updated["max_drawdown"]),1-equity/max(float(updated["peak"]),1e-9))
    updated["last_quote"]=stamp.isoformat()
    updated["last_mid"]=mid
    updated["ticks"]+=1
    if before==0 or not allowed:
        updated["negative_since"]=None
    else:
        entry=updated.get("entry_mid")
        negative=(before*(mid/float(entry)-1)
                  if entry and float(entry)>0 else 0.0)
        loss_threshold=max(PAPER_COST_FLOOR,(ask-bid)/mid*2)
        if negative < -loss_threshold:
            updated["negative_since"]=updated.get("negative_since") or stamp.isoformat()
        else:
            updated["negative_since"]=None
    return updated,traded


def _evidence(db,*,uic,state,at,kind):
    """Only technical/paper records as-of the stored quote timestamp."""
    now=_utc(at)
    # Fetch exact quote identity. Mid and spread are from actual BBO.
    quote=db.execute("""
        SELECT quote_at,bid,ask FROM lsim_hyper_quotes_1s
        WHERE provider_uic=? AND quote_at=?
    """,(uic,at)).fetchone()
    if quote is None:
        return None
    hrow=db.execute(
        "SELECT state_json,last_quote_at FROM lsim_hyper_features WHERE provider_uic=?",
        (uic,),
    ).fetchone()
    if hrow is None:
        return None
    from live_sim_hyper_vigilant_v1 import _sample_feature
    features=json.loads(hrow["state_json"])
    if _utc(features["last_quote"])<now:
        features=_sample_feature(
            features,at=at,mid=(float(quote["bid"])+float(quote["ask"]))/2)
    elif _utc(features["last_quote"])>now:
        # Parallel fast reader has advanced. Rebuilding from older, completed
        # history is preferable to letting AI see any future feature.
        samples=db.execute("""
            SELECT quote_at,bid,ask FROM lsim_hyper_quotes_1s
            WHERE provider_uic=? AND quote_at<=?
            ORDER BY quote_at DESC LIMIT 180
        """,(uic,at)).fetchall()
        from live_sim_hyper_vigilant_v1 import _features
        features=_features()
        for s in reversed(samples):
            features=_sample_feature(
                features,at=s["quote_at"],
                mid=(float(s["bid"])+float(s["ask"]))/2)
    # Warm up quote-level indicators; model never sees raw provider metadata.
    recent=db.execute("""
        SELECT quote_at,bid,ask FROM lsim_hyper_quotes_1s
        WHERE provider_uic=? AND quote_at<=? AND quote_at>=?
        ORDER BY quote_at DESC LIMIT 180
    """,(uic,at,(now-timedelta(minutes=3)).isoformat())).fetchall()
    prices=[(str(x["quote_at"]),(float(x["bid"])+float(x["ask"]))/2)
            for x in reversed(recent)]
    if len(prices)<45 or features.get("k") is None or features.get("d") is None:
        return None
    last_mid=(float(quote["bid"])+float(quote["ask"]))/2
    moves=[abs(b/a-1) for (_,a),(_,b) in zip(prices,prices[1:])]
    def net_move(window):
        reference=next((price for stamp,price in prices
                        if 0<=(now-_utc(stamp)).total_seconds()
                        and (now-_utc(stamp)).total_seconds()<=window
                        ),None)
        if reference is None:
            return None
        return round(10000*(last_mid/reference-1),2)
    entry=state.get("entry_mid")
    unrealized=(float(state["exposure"])*(last_mid/float(entry)-1)*10000
                if entry else 0.0)
    return {
        "version":VERSION,"as_of":str(at),"trigger":kind,
        "timeframe":"observed Saxo 1s quotes, causal incremental",
        "observed_ticks":len(prices),
        "price":{"mid":round(last_mid,4),
                 "spread_bps":round(10000*(float(quote["ask"])-float(quote["bid"]))/last_mid,3),
                 "change_15s_bps":net_move(15),"change_60s_bps":net_move(60),
                 "change_180s_bps":net_move(180),
                 "median_1s_abs_return_bps":round(10000*median(moves),4) if moves else None},
        "technical":{"stochastic_k":round(float(features["k"]),3),
                     "stochastic_d":round(float(features["d"]),3),
                     "stochastic_k_delta":round(float(features["k_delta"]),3),
                     "macd_20_45_15_histogram":round(float(features.get("macd_hist",0)),5),
                     "whipsaw":bool(features.get("whipsaw_active")),
                     "whipsaw_regime":"CHOP" if features.get("whipsaw_active") else "NOT_CONFIRMED"},
        "paper_portfolio":{"signed_exposure":float(state["exposure"]),
                           "unrealized_bps":round(unrealized,3),
                           "current_nav":round(float(state["equity"]),3),
                           "drawdown_pct":round(float(state["max_drawdown"])*100,3),
                           "last_model_decision":state.get("last_reason")},
        "constraints":{"targets":[-1,-0.5,0,0.5,1],
                       "one_step_max":MAX_STEP,
                       "cannot_reverse_without_flat":True,
                       "no_new_exposure_if_whipsaw":True,
                       "paper_execution":"next observed quote",
                       "can_only_recommend_not_place_real_orders":True},
    }


def technical_model_instructions():
    return (
        "You are a research-only technical analysis decision maker for one "
        "PAPER account, not a live broker or financial advisor. "
        "Choose exactly one target_exposure from {-1,-0.5,0,0.5,1} "
        "and a direction LONG, SHORT, FLAT or HOLD. "
        "Use ONLY the numeric quote, Stochastic, MACD, price momentum, "
        "whipsaw, estimated spread, unrealized P/L and drawdown in the JSON input. "
        "Never request or infer news, macroeconomics, interest rates, geopolitics, "
        "external websites, social media, private accounts or future data. "
        "A target must be justified by observable trend, reversal, continuation "
        "or risk, not an unsupported price forecast. "
        "In WHIPSAW favor no new exposure or reducing an existing one. "
        "When current position is under sustained adverse movement, decide "
        "whether to HOLD, REDUCE or FLAT based on technical evidence. "
        "A flat strategy can initiate a LONG or SHORT if there is convincing "
        "alignment between oscillator, MACD and actual price; favor FLAT "
        "when evidence conflicts or insufficient history. "
        "Be skeptical of tiny apparent edges below spread/turnover costs. "
        "Make every answer a single short JSON object matching the schema. "
        "The engine, not you, enforces all limits. This is an experiment."
    )


def _response_text(value):
    if isinstance(value.get("output_text"),str):
        return value["output_text"].strip()
    return "\n".join(
        str(item.get("text") or "")
        for message in value.get("output",[])
        for item in message.get("content",[])
        if item.get("type")=="output_text"
    ).strip()


def request_technical_decision(*,evidence,key,model=MODEL_DEFAULT,post=requests.post):
    """Single bounded AI judgement per claimed event. No tool, trading, web access."""
    response=post(
        RESPONSES_URL,
        headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"},
        json={
            "model":model,"store":False,
            "instructions":technical_model_instructions(),
            "input":json.dumps(evidence,ensure_ascii=False,sort_keys=True),
            "text":{"format":{"type":"json_schema","name":"ai_technical_paper",
                      "strict":True,"schema":{
                "type":"object","additionalProperties":False,
                "required":["direction","target_exposure","confidence","reason"],
                "properties":{
                    "direction":{"type":"string",
                                 "enum":["LONG","SHORT","FLAT","HOLD"]},
                    "target_exposure":{"type":"number","enum":[-1,-0.5,0,0.5,1]},
                    "confidence":{"type":"number"},
                    "reason":{"type":"string"},
                }}}},
        },timeout=30,
    )
    response.raise_for_status()
    answer=json.loads(_response_text(response.json()))
    if set(answer)!={"direction","target_exposure","confidence","reason"}:
        raise ValueError("invalid fields in AI response")
    if answer["direction"] not in ("LONG","SHORT","FLAT","HOLD"):
        raise ValueError("invalid AI direction")
    if answer["target_exposure"] not in (-1,-0.5,0,0.5,1):
        raise ValueError("invalid exposure")
    conf=float(answer["confidence"])
    if not math.isfinite(conf) or not 0<=conf<=1:
        raise ValueError("invalid confidence")
    if not isinstance(answer["reason"],str) or not answer["reason"].strip():
        raise ValueError("missing rationale")
    if len(answer["reason"])>700:
        raise ValueError("overlong rationale")
    # prevent direction/target ambiguity from silently creating orders
    target=float(answer["target_exposure"])
    if ((answer["direction"]=="LONG" and target<=0)
        or (answer["direction"]=="SHORT" and target>=0)
        or (answer["direction"]=="FLAT" and target!=0)):
        raise ValueError("direction and target conflict")
    return answer


def risk_gate(*,proposal,current,whipsaw):
    """Constrain all model intents. Only paper exposure can ever be affected."""
    previous=float(current)
    if proposal["direction"]=="HOLD" or float(proposal["confidence"])<0.60:
        return previous,"HOLD_OR_LOW_CONFIDENCE"
    target=float(proposal["target_exposure"])
    if previous and previous*target<0:
        return 0.0,"FLAT_BEFORE_REVERSE"
    if whipsaw and abs(target)>abs(previous)+1e-9:
        return previous,"WHIPSAW_BLOCK_ENTRY"
    if whipsaw and target*previous<0:
        return 0.0,"WHIPSAW_OPPOSITE_FLAT"
    if abs(target)>abs(previous)+MAX_STEP:
        target=math.copysign(abs(previous)+MAX_STEP,target)
    target=round(max(-MAX_EXPOSURE,min(MAX_EXPOSURE,target)),3)
    return target,"PAPER_RISK_APPROVED"


def _has_recent_ai_claim(db,uic,now):
    stamp=(now-timedelta(seconds=DECISION_COOLDOWN_SECONDS)).isoformat()
    return db.execute("""
        SELECT 1 FROM lsim_ai_technical_decisions
        WHERE provider_uic=? AND requested_at>? LIMIT 1
    """,(uic,stamp)).fetchone() is not None


def _event_kind(state,now):
    prior=state.get("last_evaluated_at")
    if prior and (now-_utc(prior)).total_seconds()<DECISION_COOLDOWN_SECONDS:
        return None
    negative=state.get("negative_since")
    if negative and (now-_utc(negative)).total_seconds()>=LOSS_SECONDS:
        return "LOSS_60S"
    if not prior or (now-_utc(prior)).total_seconds()>=ROUTINE_INTERVAL_SECONDS:
        return "TECHNICAL_REVIEW"
    return None


def _settle_quotes(db,*,uic,state,moment):
    """Append once-per-quote independent PAPER NAV with crash-safe cursor."""
    quotes=db.execute("""
        SELECT quote_at,bid,ask FROM lsim_hyper_quotes_1s
        WHERE provider_uic=? AND quote_at>? AND quote_at<=?
        ORDER BY quote_at LIMIT ?
    """,(uic,state["last_quote"],moment.isoformat(),MAX_QUOTES_PER_CYCLE)).fetchall()
    updated=state
    for quote in quotes:
        updated,traded=_mark_account(updated,quote)
        stamp=_utc(quote["quote_at"])
        if traded or int(stamp.timestamp())%10==0:
            db.execute("""
                INSERT INTO lsim_ai_technical_points(
                    provider_uic,quote_at,equity,exposure,traded,decision)
                VALUES(?,?,?,?,?,?) ON CONFLICT(provider_uic,quote_at) DO NOTHING
            """,(uic,stamp.isoformat(),updated["equity"],updated["exposure"],
                 int(traded),updated["last_reason"]))
    return updated


def _save_account(db,uic,market,state):
    db.execute("""
        INSERT INTO lsim_ai_technical_accounts(provider_uic,market_name,state_json)
        VALUES(?,?,?) ON CONFLICT(provider_uic)
        DO UPDATE SET state_json=excluded.state_json,updated_at=CURRENT_TIMESTAMP
    """,(uic,market,json.dumps(state)))


def process_ai_paper_cycle(*,db_path="pricegauger.db",now=None,
                           api_key=None,model=None,post=requests.post):
    """Mark paper NAV and make AT MOST one LLM request every 90s per market.

    A model decision is persisted after request; quote deltas are processed
    before and never rolled back on API/network/model failures.
    """
    moment=_utc(now or datetime.now(timezone.utc))
    key=api_key if api_key is not None else os.getenv("OPENAI_API_KEY","")
    model=model or os.getenv("OPENAI_MARKET_MODEL",MODEL_DEFAULT)
    with connect(db_path) as db:
        ensure_ai_schema(db)
        latest=db.execute("""
            SELECT provider_uic,market_name,MAX(quote_at) AS quote_at
            FROM lsim_hyper_quotes_1s WHERE quote_at>=? AND quote_at<=?
            GROUP BY provider_uic,market_name ORDER BY provider_uic LIMIT 2
        """,((moment-timedelta(seconds=10)).isoformat(),moment.isoformat())).fetchall()
    processed=0
    for feed in latest:
        uic=int(feed["provider_uic"])
        market=str(feed["market_name"])
        at=str(feed["quote_at"])
        if not _fresh_second(at,now=moment):
            continue
        with connect(db_path) as db:
            ensure_ai_schema(db)
            row=db.execute(
                "SELECT state_json FROM lsim_ai_technical_accounts WHERE provider_uic=?",
                (uic,)).fetchone()
            if row is None:
                quote=db.execute(
                    "SELECT bid,ask FROM lsim_hyper_quotes_1s WHERE provider_uic=? AND quote_at=?",
                    (uic,at)).fetchone()
                if quote is None:
                    continue
                baseline=db.execute(
                    "SELECT state_json FROM lsim_hyper_tracks WHERE provider_uic=? AND arm='STOCH_PRICE'",
                    (uic,)).fetchone()
                baseline_nav=(json.loads(baseline["state_json"])["equity"]
                              if baseline else None)
                _save_account(db,uic,market,_initial_state(
                    quote_time=at,mid=(float(quote["bid"])+float(quote["ask"]))/2,
                    baseline_nav=baseline_nav))
                processed+=1
                continue
            state=json.loads(row["state_json"])
            updated=_settle_quotes(db,uic=uic,state=state,moment=moment)
            if updated["last_quote"]!=state["last_quote"]:
                _save_account(db,uic,market,updated)
                processed+=1
            else:
                updated=state
            if not _fresh_second(updated["last_quote"],now=moment) or not key:
                continue
            event=_event_kind(updated,moment)
            if event is None or _has_recent_ai_claim(db,uic,moment):
                continue
            day=moment.date().isoformat()
            spent=db.execute("""
                SELECT COUNT(*) AS n FROM lsim_ai_technical_decisions
                WHERE provider_uic=? AND requested_at>=? AND requested_at<?
            """,(uic,day+"T00:00:00+00:00",
                 (moment+timedelta(days=1)).date().isoformat()+"T00:00:00+00:00")).fetchone()
            if int(spent["n"])>=MAX_DAILY_CALLS:
                continue
            evidence=_evidence(db,uic=uic,state=updated,
                               at=updated["last_quote"],kind=event)
            if evidence is None:
                continue
            # Claim budget and event *before* remote request. An interrupted
            # worker never submits multiple model calls for one quote/event.
            result=db.execute("""
                INSERT INTO lsim_ai_technical_decisions(
                    provider_uic,as_of,event_kind,requested_at,model,
                    model_status,target,confidence,reason,gate_reason,evidence_json)
                VALUES(?,?,?,?,?,'CLAIMED',NULL,NULL,'','','?')
                ON CONFLICT(provider_uic,as_of) DO NOTHING
            """,(uic,updated["last_quote"],event,moment.isoformat(),model,
                 )) if False else db.execute("""
                INSERT INTO lsim_ai_technical_decisions(
                    provider_uic,as_of,event_kind,requested_at,model,
                    model_status,target,confidence,reason,gate_reason,evidence_json)
                VALUES(?,?,?,?,?,'CLAIMED',NULL,NULL,'','','?')
                ON CONFLICT(provider_uic,as_of) DO NOTHING
            """,(uic,updated["last_quote"],event,moment.isoformat(),model))
            # Replace placeholder evidence after claim. The "?" string is not
            # used as evidence for model decisions and is overwritten before exit.
            if result.rowcount!=1:
                continue
            db.execute("""
                UPDATE lsim_ai_technical_decisions SET evidence_json=?
                WHERE provider_uic=? AND as_of=?
            """,(json.dumps(evidence,sort_keys=True),
                 uic,updated["last_quote"]))
            updated["last_evaluated_at"]=moment.isoformat()
            updated["ai_calls"]=int(updated["ai_calls"])+1
            if event=="LOSS_60S":
                updated["loss_triggers"]=int(updated["loss_triggers"])+1
            _save_account(db,uic,market,updated)
            claimed_as_of=updated["last_quote"]
        # Remote LLM request happens only after a committed reservation.
        try:
            recommendation=request_technical_decision(
                evidence=evidence,key=key,model=model,post=post)
            status="READY"
        except Exception as exc:
            recommendation=None
            status="ERROR_"+type(exc).__name__[:35]
        response_at=_utc(datetime.now(timezone.utc) if now is None else now)
        with connect(db_path) as db:
            row=db.execute(
                "SELECT state_json FROM lsim_ai_technical_accounts WHERE provider_uic=?",
                (uic,)).fetchone()
            if row is None:
                continue
            state=json.loads(row["state_json"])
            newest=db.execute(
                "SELECT MAX(quote_at) AS stamp FROM lsim_hyper_quotes_1s WHERE provider_uic=?",
                (uic,)).fetchone()["stamp"]
            age=(_utc(newest)-_utc(claimed_as_of)).total_seconds() if newest else 9999
            if age>MAX_REQUEST_AGE_SECONDS:
                status="STALE_RESPONSE"
            if recommendation is None or status!="READY":
                state["rejected_requests"]+=1
                state["last_model_status"]=status
                db.execute("""
                    UPDATE lsim_ai_technical_decisions
                    SET model_status=?,gate_reason=?
                    WHERE provider_uic=? AND as_of=?
                """,(status,"NO_EXECUTION",uic,claimed_as_of))
            else:
                # Re-check known last-model position and current whipsaw.
                hrow=db.execute(
                    "SELECT state_json FROM lsim_hyper_features WHERE provider_uic=?",
                    (uic,)).fetchone()
                whipsaw=(bool(json.loads(hrow["state_json"]).get("whipsaw_active"))
                         if hrow else True)
                proposed,gate=risk_gate(
                    proposal=recommendation,current=float(state["exposure"]),
                    whipsaw=whipsaw)
                state["pending"]=proposed
                state["pending_as_of"]=claimed_as_of if abs(proposed-state["exposure"])>1e-9 else None
                state["accepted_decisions"]+=1
                state["last_reason"]=recommendation["reason"]
                state["last_model_status"]="READY"
                db.execute("""
                    UPDATE lsim_ai_technical_decisions SET
                        model_status='READY',target=?,confidence=?,
                        reason=?,gate_reason=?
                    WHERE provider_uic=? AND as_of=?
                """,(proposed,float(recommendation["confidence"]),
                     recommendation["reason"],gate,uic,claimed_as_of))
            _save_account(db,uic,market,state)
    return processed


def ai_technical_snapshot(*,db_path="pricegauger.db"):
    with connect(db_path) as db:
        ensure_ai_schema(db)
        accounts=[dict(x) for x in db.execute("""
            SELECT provider_uic,market_name,state_json FROM lsim_ai_technical_accounts
            ORDER BY provider_uic
        """).fetchall()]
        decisions=[dict(x) for x in db.execute("""
            SELECT provider_uic,as_of,event_kind,model,model_status,
                   target,confidence,reason,gate_reason
            FROM lsim_ai_technical_decisions
            ORDER BY as_of DESC LIMIT 100
        """).fetchall()]
        points=[dict(x) for x in db.execute("""
            SELECT provider_uic,quote_at,equity,exposure,traded,decision
            FROM lsim_ai_technical_points
            ORDER BY quote_at DESC LIMIT 800
        """).fetchall()]
    for row in accounts:
        row.update(json.loads(row.pop("state_json")))
    return accounts,decisions,list(reversed(points))
