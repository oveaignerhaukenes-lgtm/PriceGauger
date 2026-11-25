"""Independent forward simulation for the first canonical V3 strategy family.

No LIVE order calls and no LIVE state writes. Calibration terms are explicit
research inputs; the entire trial is labeled SCENARIO, never validated LIVE.
Each decision and account transition is one atomic append-only event.
"""
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from uuid import uuid4

from database import connect, run_postgres_schema_once_v1
from live_mirror_registry_v1 import mirror_snapshot, _stamp, _json
from live_mirror_broker_v1 import MirrorTerms, MirrorAccount, MirrorQuote, execute_target
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from autotrader_mtf_entry_shadow_v2 import closed_bars_v2, macd_observations_v2
from autotrader_v3_macd_stoch_v21 import macd_stoch_v21_target_v3
from autotrader_v3_macd_stoch_v21_split_v3 import (
    LONG_KEY_V3_PRICE_HIST, SHORT_KEY_V3_PRICE_HIST,
    long_flat_target_v3_price_hist, short_flat_target_v3_price_hist,
)
from autotrader_v3_macd_trailing_v1 import MacdTrailingConfigV3
from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_regime_gate_v1 import RegimePolicyV1, decide_regime_entry_v1, classify_regime_v1
from autotrader_v3_protective_live_v1 import impulse_evidence_v3, ProtectiveEvidenceV3, ProtectiveModifierV3, IMPULSE_LOOKBACK_S

SUPPORTED = {
    "macd-stoch-v2-1": macd_stoch_v21_target_v3,
    LONG_KEY_V3_PRICE_HIST: long_flat_target_v3_price_hist,
    SHORT_KEY_V3_PRICE_HIST: short_flat_target_v3_price_hist,
}
MODEL_VERSION = "canonical-v3-mirror-scenario-v1"


def ensure_execution_schema(db_path):
    def initialize():
        with connect(db_path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS pg_live_mirror_session_v1(
                session_id TEXT PRIMARY KEY, mirror_id TEXT NOT NULL,
                instance_id TEXT NOT NULL, terms_json TEXT NOT NULL,
                started_at TEXT NOT NULL, initial_cash DOUBLE PRECISION NOT NULL,
                active BOOLEAN NOT NULL, last_bar TEXT NOT NULL,
                state_json TEXT NOT NULL, pending_json TEXT,
                last_status TEXT NOT NULL, revision INTEGER NOT NULL)""")
            db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS pg_mirror_one_session_v1
                ON pg_live_mirror_session_v1(instance_id) WHERE active=TRUE""")
            db.execute("""CREATE TABLE IF NOT EXISTS pg_live_mirror_event_v1(
                session_id TEXT NOT NULL, decision_bar TEXT NOT NULL,
                decided_at TEXT NOT NULL, outcome TEXT NOT NULL,
                event_json TEXT NOT NULL, PRIMARY KEY(session_id,decision_bar))""")
    run_postgres_schema_once_v1("pg_live_mirror_execution_v1",initialize)


def _scenario_terms(cfg, terms):
    terms = dict(terms)
    terms["capital_cap_nok"] = float(cfg["capital"]["budget_nok"])*float(cfg["capital"]["exposure_pct"])/100
    return MirrorTerms(**terms)


def support_reason(cfg):
    strategy = cfg.get("strategy") or {}
    if strategy.get("strategy_key") not in SUPPORTED:
        return "UNSUPPORTED_STRATEGY"
    if strategy.get("control_mode") != "Manuell" or set(json.loads(strategy.get("modifiers_json") or "[]"))-{"impulse-exit"}:
        return "UNSUPPORTED_MODIFIERS_OR_MODE"
    if strategy.get("timeframe") not in ("1m","2m","3m","5m","10m","15m","30m"):
        return "UNSUPPORTED_CLOCK"
    if cfg.get("missing_sources"):
        return "WAIT_CONFIG"
    return None


def _policy(cfg, instance_id):
    key=cfg["strategy"]["strategy_key"]
    raw=cfg.get("regime") or {}
    # Preserve running main's existing legacy strategy-bound policy semantics.
    # A policy mismatch is explicitly unsupported rather than guessing whether
    # the deployed instance-scope migration has occurred.
    stop=cfg.get("stop") or {}
    if any(p and p.get("strategy_key")!=key for p in (raw,stop)):
        raise ValueError("ambiguous legacy filter binding")
    states=tuple(s for s in ("BULL","BEAR","SIDEWAYS") if raw.get("allow_"+s.lower()))
    return RegimePolicyV1(instance_id,key,mode=raw.get("mode","OFF"),
                          allowed_states=states,trend_only=bool(raw.get("trend_only")),
                          block_unknown=bool(raw.get("block_unknown"))),stop.get("mode","GO")


def _features(cfg, market, now, db_path, cache):
    tf=int(cfg["strategy"]["timeframe"][:-1])
    instrument=int(cfg["boundary"]["instrument_id"])
    cache_key=(instrument,tf)
    if cache_key not in cache:
        source=CanonicalMarketBarStoreV2(db_path).load_instrument_range(
            instrument_id=instrument,start=now-timedelta(days=14),end=now,limit=20000)
        source=tuple(b for b in source if _stamp(b.bar_time)+timedelta(minutes=1)<=now)
        closed=closed_bars_v2(tuple(b.point for b in source),market=market,
                             timeframe_minutes=tf) if source else ()
        observations=macd_observations_v2(closed,timeframe_minutes=tf) if closed else ()
        cache[cache_key]=(source,closed,observations)
    return cache[cache_key]


def decide_target(cfg, account, source, closed, observations, *, now, terms, market):
    """Same production strategy function, but use actual independent SIM inventory.

    Using last completed observation for prior evidence is a documented
    research choice; LIVE durable prior memory may differ after rejection.
    """
    key=cfg["strategy"]["strategy_key"]
    settings=cfg["strategy"]
    args=dict(current_target=TargetInventoryV3(account.inventory),
              observation=observations[-1],
              previous_observation=observations[-2] if len(observations)>1 else None,
              bars=closed,
              config=MacdTrailingConfigV3(tranche=terms.minimum_lots,
                                          max_inventory=terms.minimum_lots*10))
    if key != "macd-stoch-v2-1":
        args.update(source_bars=source,market_name=market,
                    regime_timeframe_minutes=int(settings["regime_timeframe"][:-1]),
                    exit_timeframe_minutes=int(settings["exit_timeframe"][:-1]))
    result=SUPPORTED[key](**args)
    raw=result.target.amount
    target=raw
    # Opposite direction always flattens first.
    if target*account.inventory<0:
        target=0.0
    reason=result.action
    if abs(target)>abs(account.inventory)+1e-9:
        policy,stop=_policy(cfg,"mirror")
        if stop=="STOP":
            target=account.inventory
            reason="STOP_VETO"
        elif policy.mode=="LIVE":
            state,_=classify_regime_v1(source,now=now)
            gate=decide_regime_entry_v1(policy,state=state,
                                       direction="LONG" if target>0 else "SHORT")
            if not gate.allow_new_exposure:
                target=account.inventory
                reason="REGIME_VETO:"+state
    return raw,target,reason,result.reason


def _read_sessions(db_path):
    with connect(db_path) as db:
        return [dict(r) for r in db.execute("SELECT * FROM pg_live_mirror_session_v1 WHERE active=TRUE").fetchall()]


def _retire(session, status, db_path):
    with connect(db_path) as db:
        db.execute("""UPDATE pg_live_mirror_session_v1 SET active=FALSE,last_status=?,
            revision=revision+1 WHERE session_id=? AND revision=? AND active=TRUE""",
            (status,session["session_id"],session["revision"]))


def _start(row,cfg,terms,now,db_path,model_source="explicit"):
    # Require the fresh, flat account reference and a new forward bar after start.
    ref=json.loads(row["reference_json"])
    truth=ref.get("account")
    if not truth or row["status"]!="WAIT_CALIBRATION" or (now-_stamp(row["observed_at"])).total_seconds()>90:
        return None
    if (now-_stamp(truth["observed_at"])).total_seconds()>360:
        return None
    cash=float(truth["total_value"])
    sid="scenario:"+model_source+":"+uuid4().hex
    clock=now.isoformat()
    state=_json(asdict(MirrorAccount(cash)))
    with connect(db_path) as db:
        result=db.execute("""INSERT INTO pg_live_mirror_session_v1
            (session_id,mirror_id,instance_id,terms_json,started_at,initial_cash,active,last_bar,
             state_json,pending_json,last_status,revision) VALUES(?,?,?,?,?,?,TRUE,?,?,NULL,'WARMUP',0)
            ON CONFLICT DO NOTHING""",(sid,row["mirror_id"],row["instance_id"],_json(asdict(terms)),
            clock,cash,clock,state))
    return sid if result.rowcount==1 else None


def _quotes(cfg,decision_at,now,db_path):
    b=cfg["boundary"]
    with connect(db_path) as db:
        rows=db.execute("""SELECT quote_at,received_at,bid,ask FROM lsim_hyper_quotes_1s
            WHERE provider_uic=? AND asset_type=? AND received_at>=? AND received_at<=?
            ORDER BY received_at,quote_at LIMIT 200""",
            (b["uic"],b["asset_type"],decision_at.isoformat(),now.isoformat())).fetchall()
    return tuple(MirrorQuote(_stamp(r["quote_at"]),_stamp(r["received_at"]),
                             float(r["bid"]),float(r["ask"])) for r in rows)


def _update(session, *, db_path, last_bar, pending, account, status, event=None, impulse=None):
    """Optimistic CAS and event insertion in one transaction. No duplicate fills."""
    state=asdict(account)
    if impulse is not None:
        state["impulse"]=impulse
    with connect(db_path) as db:
        changed=db.execute("""UPDATE pg_live_mirror_session_v1 SET last_bar=?,
            pending_json=?,state_json=?,last_status=?,revision=revision+1
            WHERE session_id=? AND revision=? AND active=TRUE""",
            (last_bar,None if pending is None else _json(pending),_json(state),
             status,session["session_id"],session["revision"]))
        if changed.rowcount!=1:
            return False
        if event is not None:
            db.execute("""INSERT INTO pg_live_mirror_event_v1
                (session_id,decision_bar,decided_at,outcome,event_json) VALUES(?,?,?,?,?)""",
                (session["session_id"],event["bar"],event["decided_at"],status,_json(event)))
    return True


def _impulse(cfg, account, previous, now, db_path, cache):
    """Same pure protective detector as LIVE; session-local pause memory."""
    b=cfg["boundary"]
    key=("impulse",b["uic"],b["asset_type"])
    if key not in cache:
        with connect(db_path) as db:
            cache[key]=db.execute("""SELECT quote_at,received_at,bid,ask FROM lsim_hyper_quotes_1s
                WHERE provider_uic=? AND asset_type=? AND quote_at>=? AND quote_at<=?
                AND received_at<=? ORDER BY quote_at LIMIT 120""",
                (b["uic"],b["asset_type"],(now-timedelta(seconds=IMPULSE_LOOKBACK_S)).isoformat(),
                 now.isoformat(),now.isoformat())).fetchall()
    paused=previous.get("status")=="IMPULSE_PAUSE"
    evidence,quiet=impulse_evidence_v3(rows=cache[key],now=now,
        actual_amount=account.inventory,was_paused=paused,
        quiet_since=_stamp(previous.get("quiet_since")))
    if paused and evidence.status=="DATA_MISSING":
        evidence=ProtectiveEvidenceV3("impulse-exit","IMPULSE_PAUSE",
                                    "BBO stale during protective pause; remain FLAT")
    memory={"status":evidence.status,"quiet_since":quiet.isoformat() if quiet else None}
    return evidence,memory


def _advance(session,row,cfg,terms,now,db_path,cache):
    state=json.loads(session["state_json"])
    previous=state.pop("impulse",{})
    account=MirrorAccount(**state)
    pending=json.loads(session["pending_json"]) if session["pending_json"] else None
    enabled="impulse-exit" in json.loads(cfg["strategy"].get("modifiers_json") or "[]")
    memory=previous if enabled else None
    if pending is not None:
        decided=_stamp(pending["decided_at"])
        fill=execute_target(account,pending["approved"],decided_at=decided,
             quotes=_quotes(cfg,decided,now,db_path),now=now,terms=terms)
        if fill.status=="WAIT_QUOTE":
            return False
        event={**pending,"price":fill.price,"fill_received_at":fill.received_at,
               "inventory_after":fill.account.inventory,"cash_after":fill.account.cash_nok,
               "fees_total":fill.account.fees_nok,"realized_gross":fill.account.realized_nok}
        return _update(session,db_path=db_path,last_bar=pending.get("cursor_bar",pending["bar"]),pending=None,
                       account=fill.account,status=fill.status,event=event,impulse=memory)
    # Evaluate protection on each research cycle, not merely on closed bars.
    # Protective exits have their own timestamps and do not consume a bar.
    evidence=None
    if enabled:
        evidence,memory=_impulse(cfg,account,previous,now,db_path,cache)
        if evidence.status=="IMPULSE_PAUSE" and abs(account.inventory)>1e-9:
            event=dict(bar=now.isoformat(),cursor_bar=session["last_bar"],
                       decided_at=now.isoformat(),raw=account.inventory,approved=0.,
                       inventory_before=account.inventory,action="IMPULSE_PAUSE",
                       reason=evidence.reason,kind="PROTECTIVE_TICK")
            return _update(session,db_path=db_path,last_bar=session["last_bar"],pending=event,
                           account=account,status="PENDING_QUOTE",impulse=memory)
    def preserve_memory():
        if enabled and memory!=previous:
            return _update(session,db_path=db_path,last_bar=session["last_bar"],
                           pending=None,account=account,status=session["last_status"],impulse=memory)
        return False
    tf=int(cfg["strategy"]["timeframe"][:-1])
    latest_boundary=now.replace(second=0,microsecond=0)-timedelta(minutes=now.minute%tf)
    if latest_boundary<=_stamp(session["last_bar"]) or now-latest_boundary>timedelta(seconds=25):
        return preserve_memory()
    source,closed,obs=_features(cfg,row["market_name"],now,db_path,cache)
    if len(obs)<2 or obs[-1].closed_at!=latest_boundary:
        return preserve_memory()
    bar=obs[-1].closed_at.isoformat()
    raw,approved,action,reason=decide_target(cfg,account,source,closed,obs,
                                           now=now,terms=terms,market=row["market_name"])
    if evidence is not None:
        adjusted,detail=ProtectiveModifierV3("impulse-exit",evidence,account.inventory).apply(
            None,TargetInventoryV3(approved))
        if abs(adjusted.amount-approved)>1e-9:
            action=evidence.status
            reason=detail
        approved=adjusted.amount
    event=dict(bar=bar,decided_at=now.isoformat(),raw=raw,approved=approved,
               inventory_before=account.inventory,action=action,reason=reason)
    if evidence is not None:
        event["impulse_status"]=evidence.status
    if abs(approved-account.inventory)<1e-9:
        event.update(inventory_after=account.inventory,cash_after=account.cash_nok,
                     fees_total=account.fees_nok,realized_gross=account.realized_nok)
        return _update(session,db_path=db_path,last_bar=bar,pending=None,account=account,
                       status="NO_CHANGE",event=event,impulse=memory)
    return _update(session,db_path=db_path,last_bar=bar,pending=event,
                   account=account,status="PENDING_QUOTE",impulse=memory)


def run_mirror_execution_cycle(*,db_path="pricegauger.db",now=None,scenario_terms=None,
                               observed_terms=None):
    """Independent scenario execution, never auto-arm or change LIVE.

    Explicit terms override observed candidates. An observed model is frozen
    for its whole configuration session. No terms means no virtual trading.
    """
    now=now or datetime.now(timezone.utc)
    raw=scenario_terms if scenario_terms is not None else json.loads(
        os.getenv("PRICEGAUGER_MIRROR_SCENARIO_TERMS","{}"))
    observed_terms=observed_terms or {}
    rows=mirror_snapshot(db_path=db_path)
    if rows is None:
        return {"status":"WAIT_REFERENCE","processed":0}
    if any(not _stamp(r["observed_at"]) or not 0 <= (now-_stamp(r["observed_at"])).total_seconds() <= 90 for r in rows):
        return {"status":"STALE_REFERENCE","processed":0}
    ensure_execution_schema(db_path)
    sessions={s["instance_id"]:s for s in _read_sessions(db_path)}
    active={r["instance_id"]:r for r in rows}
    for identity,s in list(sessions.items()):
        if identity not in active or active[identity]["mirror_id"]!=s["mirror_id"]:
            _retire(s,"REFERENCE_CHANGED",db_path)
            sessions.pop(identity)
    cache={}
    statuses={}
    processed=0
    for identity,row in active.items():
        reason=None
        s=sessions.get(identity)
        try:
            cfg=json.loads(row["config_json"])
            reason=support_reason(cfg)
            if reason:
                raise ValueError(reason)
            _policy(cfg,identity)
            instrument=str(cfg["boundary"]["uic"])+":"+cfg["boundary"]["asset_type"]
            instance_key="instance:"+identity
            explicit=raw.get(instance_key,raw.get(instrument))
            if explicit is not None:
                model_source="explicit"
                terms=_scenario_terms(cfg,explicit)
            elif s and s["session_id"].startswith("scenario:observed:"):
                model_source="observed"
                terms=MirrorTerms(**json.loads(s["terms_json"]))
            elif instance_key in observed_terms:
                model_source="observed"
                terms=_scenario_terms(cfg,observed_terms[instance_key])
            else:
                raise ValueError("no observed or explicit terms")
        except (ValueError,KeyError,TypeError):
            statuses[identity]=reason or "WAIT_TERMS_OR_POLICY"
            if s:
                _retire(s,statuses[identity],db_path)
            continue
        if s and s["session_id"].startswith("scenario:"+model_source+":") and s["terms_json"]==_json(asdict(terms)):
            try:
                processed+=int(_advance(s,row,cfg,terms,now,db_path,cache))
                statuses[identity]="SCENARIO_"+model_source.upper()
            except Exception as exc:
                statuses[identity]="SCENARIO_ERROR"
                logging.getLogger(__name__).warning("Mirror scenario error instance=%s type=%s",identity,type(exc).__name__)
        else:
            if s:
                _retire(s,"TERMS_CHANGED",db_path)
            statuses[identity]="SCENARIO_STARTED" if _start(row,cfg,terms,now,db_path,model_source) else row["status"]
    return {"status":"SCENARIO_ONLY","processed":processed,"instances":statuses}


def execution_snapshot(*,db_path="pricegauger.db"):
    try:
        return _read_sessions(db_path)
    except Exception:
        return None
