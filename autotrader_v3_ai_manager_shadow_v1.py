"""V3 AI loss-manager: actual OpenAI technical review, SHADOW only.

Observes account-scoped Saxo loss episodes and asks the existing paper technical
model for HOLD/REDUCE/FLAT/REVERSE advice; persists immutable evidence via the
V3 AI memory. It NEVER imports or invokes V3 execution/order authority.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import isfinite
import logging
import time

from autotrader_v3_ai_decision_memory_v1 import record_ai_decision_v1
from autotrader_v3_config_v1 import load_autotrader_config_v3
from autotrader_v3_instance_registry_v1 import load_v3_instances_v1
from autotrader_v3_live_authority_v1 import live_authority_armed_v3
from autotrader_v3_live_saxo_v1 import configured_live_pilot_client_v3
from autotrader_v3_reset_on_loss_v1 import open_pnl_from_net_position_v3
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from config import openai_api_key, openai_market_model
from database import connect
from live_sim_ai_technical_trader_v1 import request_technical_decision
from trading_desk import ChartBar, utc
from trading_desk_indicators import calculate_indicators

LOGGER=logging.getLogger("pricegauger.v3.ai_shadow")
DEFAULT_TRIGGER_SECONDS=60
MIN_TRIGGER_SECONDS=15
MAX_TRIGGER_SECONDS=180
REVIEW_COOLDOWN_SECONDS=180
MAX_REVIEWS_PER_HOUR=4
POLL_SECONDS=30


def ensure_ai_shadow_schema_v1(db_path="pricegauger.db"):
    with connect(db_path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS pg_v3_ai_shadow_settings_v1 (
            instance_id TEXT PRIMARY KEY,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            trigger_seconds INTEGER NOT NULL DEFAULT 60,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS pg_v3_ai_shadow_watch_v1 (
            instance_id TEXT PRIMARY KEY,
            identity TEXT NOT NULL,
            negative_since TEXT,
            last_seen TEXT NOT NULL,
            last_reviewed TEXT,
            last_review_pnl DOUBLE PRECISION,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")


def shadow_settings_v1(instance_id: str, *, db_path="pricegauger.db") -> dict:
    ensure_ai_shadow_schema_v1(db_path)
    with connect(db_path) as db:
        row=db.execute("""SELECT enabled,trigger_seconds
            FROM pg_v3_ai_shadow_settings_v1 WHERE instance_id=?""",
            (str(instance_id),)).fetchone()
    if row is None:
        return {"enabled":True,"trigger_seconds":DEFAULT_TRIGGER_SECONDS}
    value=dict(row)
    return {"enabled":bool(value["enabled"]),
            "trigger_seconds":int(value["trigger_seconds"])}


def save_shadow_settings_v1(
    *, instance_id: str, enabled: bool, trigger_seconds: int,
    db_path="pricegauger.db",
):
    delay=int(trigger_seconds)
    if not MIN_TRIGGER_SECONDS<=delay<=MAX_TRIGGER_SECONDS:
        raise ValueError("AI trigger must be within 15..180 seconds")
    ensure_ai_shadow_schema_v1(db_path)
    with connect(db_path) as db:
        db.execute("""INSERT INTO pg_v3_ai_shadow_settings_v1
            (instance_id,enabled,trigger_seconds) VALUES(?,?,?)
            ON CONFLICT(instance_id) DO UPDATE SET
            enabled=excluded.enabled,
            trigger_seconds=excluded.trigger_seconds,
            updated_at=CURRENT_TIMESTAMP""",
            (str(instance_id),bool(enabled),delay))


def _stamp(value):
    return utc(value).isoformat()


def claim_due_loss_review_v1(
    *, instance_id: str, identity: str, open_pnl: float,
    when: datetime, trigger_seconds: int, db_path="pricegauger.db",
) -> bool:
    """Persist continuous negative episode; claim once per cooldown window.

    A restart preserves the timer. A different strategy/position identity, a
    positive P/L, or a >90s sampling gap resets the episode.
    """
    if not isfinite(float(open_pnl)):
        return False
    clock=utc(when)
    ensure_ai_shadow_schema_v1(db_path)
    with connect(db_path) as db:
        row=db.execute("""SELECT identity,negative_since,last_seen,
            last_reviewed,last_review_pnl FROM pg_v3_ai_shadow_watch_v1
            WHERE instance_id=?""",(instance_id,)).fetchone()
        old=dict(row) if row else {}
        same=(old.get("identity")==identity and
              old.get("last_seen") is not None and
              0 <= (clock-utc(old["last_seen"])).total_seconds()<=90)
        since=utc(old["negative_since"]) if same and old.get("negative_since") else clock
        last=utc(old["last_reviewed"]) if same and old.get("last_reviewed") else None
        if open_pnl>=0:
            since=None
            last=None
        due=bool(
            since is not None
            and (clock-since).total_seconds()>=int(trigger_seconds)
            and (last is None or (clock-last).total_seconds()>=REVIEW_COOLDOWN_SECONDS)
        )
        db.execute("""INSERT INTO pg_v3_ai_shadow_watch_v1
            (instance_id,identity,negative_since,last_seen,last_reviewed,last_review_pnl)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(instance_id) DO UPDATE SET
              identity=excluded.identity,
              negative_since=excluded.negative_since,
              last_seen=excluded.last_seen,
              last_reviewed=excluded.last_reviewed,
              last_review_pnl=excluded.last_review_pnl,
              updated_at=CURRENT_TIMESTAMP""",(
                instance_id,identity,_stamp(since) if since else None,
                _stamp(clock),_stamp(clock) if due else (_stamp(last) if last else None),
                float(open_pnl) if due else (old.get("last_review_pnl") if same else None),
            ))
    return due


def position_direction_and_size_v1(row) -> float:
    base=row.get("NetPositionBase") or {}
    long=base.get("AmountLong")
    short=base.get("AmountShort")
    if long is not None or short is not None:
        a=float(long or 0)-float(short or 0)
    else:
        direction=str(base.get("OpeningDirection") or "").lower()
        if direction not in ("buy","sell"):
            raise ValueError("Saxo direction missing")
        a=float(base.get("Amount") or 0)*(1 if direction=="buy" else -1)
    if not isfinite(a):
        raise ValueError("Saxo inventory nonfinite")
    return a


def _technical_evidence(
    *, instance, config, broker_pnl: float, actual: float,
    observed_at: datetime, db_path: str,
):
    timeframe=int(str(config.timeframe).removesuffix("m")) if config.timeframe!="1h" else 60
    lookback_hours=min(30,max(5,1+timeframe*45/60))
    raw=CanonicalMarketBarStoreV2(db_path).load_instrument_range(
        instrument_id=int(instance.instrument_id),
        start=observed_at-timedelta(hours=lookback_hours),
        end=observed_at,limit=2000)
    cutoff=observed_at.replace(second=0,microsecond=0)
    chart=tuple(ChartBar(
        market=instance.market_name,bar_time=x.bar_time,
        open=x.open,high=x.high,low=x.low,close=x.close,volume=x.volume)
        for x in raw if utc(x.bar_time)<cutoff)
    if len(chart)<40 or (observed_at-utc(chart[-1].bar_time)).total_seconds()>130:
        return None
    # Reuse exact complete-bar resampler used by the user-facing V3 chart.
    # Imported locally so standard trading worker startup stays independent of UI.
    from autotrader_v3_instance_inspection_v1 import resample_complete_candles_v1
    signal=resample_complete_candles_v1(chart,timeframe_minutes=timeframe,now=observed_at)
    if len(signal)<36:
        return None
    ind=calculate_indicators(signal)
    if not (ind.macd and ind.macd_signal and ind.macd_histogram and
            ind.stochastic_k and ind.stochastic_d):
        return None
    last=signal[-1]
    if (observed_at-utc(last.bar_time)).total_seconds()>timeframe*60+130:
        return None
    hist=[float(p.value) for p in ind.macd_histogram[-5:]]
    close=[float(x.close) for x in chart[-18:]]
    returns=[(close[i]/close[i-1]-1.)*100.
             for i in range(1,len(close))]
    as_of=min(observed_at,utc(last.bar_time)+timedelta(minutes=timeframe))
    payload={
        "source":"V3_SHADOW_ACCOUNT_SCOPED",
        "as_of":_stamp(as_of),
        "strategy":config.strategy_key,
        "timeframe":config.timeframe,
        "market":instance.market_name,
        "position":{"direction":"LONG" if actual>0 else "SHORT",
                    "quantity_abs":round(abs(actual),6),
                    "saxo_open_pnl_account_currency":round(float(broker_pnl),4)},
        "technical":{
            "bar_close":float(last.close),
            "macd":float(ind.macd[-1].value),
            "signal":float(ind.macd_signal[-1].value),
            "macd_histogram_last_5":hist,
            "stochastic_k":float(ind.stochastic_k[-1].value),
            "stochastic_d":float(ind.stochastic_d[-1].value),
            "last_18_1m_closes":close,
            "last_17_1m_returns_pct":returns,
            "volatility_recent_pct":max(abs(r) for r in returns),
        },
        "limitations":"Only completed canonical bars; no verified subminute flow or forecast. SHADOW: no orders.",
    }
    return as_of,payload


def _classify_shadow_advice(answer: dict, actual: float) -> str:
    direction=str(answer["direction"]).upper()
    proposed=float(answer["target_exposure"])
    if direction=="HOLD" or float(answer["confidence"])<.60:
        return "HOLD"
    if direction=="FLAT" or abs(proposed)<1e-12:
        return "FLAT"
    if proposed*actual<0:
        return "REVERSE"
    if abs(proposed)<1 and proposed*actual>0:
        return "REDUCE"
    return "HOLD"


def review_shadow_instance_once_v1(
    *, instance, broker, when: datetime, db_path="pricegauger.db",
    model_callback=None, api_key="", model="gpt-5-mini",
) -> str:
    """Run one read-only observation; only loss triggers a genuine model call."""
    settings=shadow_settings_v1(instance.instance_id,db_path=db_path)
    if not settings["enabled"]:
        return "DISABLED"
    if not live_authority_armed_v3(instance.instance_id,db_path=db_path):
        return "NOT_ARMED"
    config=load_autotrader_config_v3(instance.instance_id,db_path=db_path)
    rows=broker.net_positions_exact(
        account_id=instance.account_id,uic=instance.uic,
        asset_type=instance.asset_type)
    if not rows:
        claim_due_loss_review_v1(instance_id=instance.instance_id,
            identity="FLAT",open_pnl=0.,when=when,trigger_seconds=settings["trigger_seconds"],
            db_path=db_path)
        return "FLAT"
    actual=position_direction_and_size_v1(rows[0])
    if abs(actual)<1e-12:
        return "FLAT"
    pnl=float(open_pnl_from_net_position_v3(rows[0]))
    identity=(f"{instance.account_id}|{instance.instrument_id}|{config.strategy_key}|"
              f"{config.timeframe}|{actual:.7g}")
    due=claim_due_loss_review_v1(
        instance_id=instance.instance_id,identity=identity,
        open_pnl=pnl,when=when,trigger_seconds=settings["trigger_seconds"],db_path=db_path)
    if not due:
        return "WAITING"
    # Genuine adverse P/L has persisted. Do not call the model on missing bars.
    technical=_technical_evidence(
        instance=instance,config=config,broker_pnl=pnl,actual=actual,
        observed_at=utc(when),db_path=db_path)
    if technical is None:
        return "STALE_TECHNICAL_DATA"
    as_of,evidence=technical
    if not api_key and model_callback is None:
        return "NO_AI_KEY"
    # The existing Live-Sim technical model uses a strict JSON response contract.
    evaluator=model_callback or (lambda snapshot:request_technical_decision(
        evidence=snapshot,key=api_key,model=model))
    answer=evaluator(evidence)
    advice=_classify_shadow_advice(answer,actual)
    confidence=float(answer["confidence"])
    reason=str(answer["reason"]).strip()
    if not 0<=confidence<=1 or not reason:
        raise ValueError("unusable model advice")
    decision_id=(f"ai-shadow:{instance.instance_id}:"
                 f"{int(utc(when).timestamp())}:"
                 f"{config.strategy_key}")
    record_ai_decision_v1(
        decision_id=decision_id,instance_id=instance.instance_id,
        account_id=instance.account_id,instrument_id=instance.instrument_id,
        strategy_key=config.strategy_key,evaluated_at=when,evidence_as_of=as_of,
        model_id=model,mode="SHADOW",action=advice,confidence=confidence,
        reason=reason,evidence={
            "snapshot":evidence,
            "model_proposal":{"direction":answer["direction"],
                              "target_exposure":answer["target_exposure"]},
            "review_scope":"SIM_SHADOW_ONLY_NO_LIVE_EXECUTION",
        },db_path=db_path)
    return advice


def run_v3_ai_shadow_once_v1(*, db_path="pricegauger.db", when=None,
                            broker=None, model_callback=None,
                            api_key=None, model=None) -> dict:
    """One bounded account-scoped pass; failures remain isolated per instance."""
    clock=utc(when or datetime.now(timezone.utc))
    key=openai_api_key() if api_key is None else api_key
    model_name=model or openai_market_model()
    if not key and model_callback is None:
        return {"status":"NO_AI_KEY","seen":0,"reviewed":0}
    live_broker=broker if broker is not None else configured_live_pilot_client_v3()
    if live_broker is None:
        return {"status":"NO_SAXO_CLIENT","seen":0,"reviewed":0}
    seen=reviewed=failed=0
    for inst in load_v3_instances_v1(db_path=db_path):
        if not inst.enabled:
            continue
        try:
            result=review_shadow_instance_once_v1(
                instance=inst,broker=live_broker,when=clock,db_path=db_path,
                model_callback=model_callback,api_key=key,model=model_name)
            if result in ("HOLD","REDUCE","FLAT","REVERSE"):
                reviewed+=1
            seen+=1
        except Exception as exc:
            failed+=1
            # Never log raw broker responses or model payloads.
            LOGGER.warning("V3 AI shadow failed type=%s",
                           type(exc).__name__)
    return {"status":"OK" if not failed else "PARTIAL",
            "seen":seen,"reviewed":reviewed,"failed":failed}


def run_v3_ai_shadow_forever_v1(*, db_path="pricegauger.db",
                              stop_event, interval_seconds=POLL_SECONDS):
    while not stop_event.is_set():
        try:
            result=run_v3_ai_shadow_once_v1(db_path=str(db_path))
            if result["reviewed"] or result.get("failed"):
                LOGGER.info("V3 AI shadow status=%s seen=%s reviewed=%s failed=%s",
                    result["status"],result["seen"],result["reviewed"],
                    result.get("failed",0))
        except Exception as exc:
            LOGGER.warning("V3 AI shadow poll failed kind=%s",type(exc).__name__)
        stop_event.wait(max(15,int(interval_seconds)))


__all__=["ensure_ai_shadow_schema_v1","shadow_settings_v1","save_shadow_settings_v1",
         "claim_due_loss_review_v1","position_direction_and_size_v1",
         "review_shadow_instance_once_v1","run_v3_ai_shadow_once_v1",
         "run_v3_ai_shadow_forever_v1"]
