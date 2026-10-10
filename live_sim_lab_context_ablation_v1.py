"""Prospective, read-only Context x Technical paired ablations for Live-Sim Lab.

Five frozen candidate baselines, four equal-start paper tracks per candidate:
BASE / MACRO / GEO / BOTH. Reuses AI-derived canonical Context v2 evidence
and known-in-advance scheduled macro releases. Never imports trading/execution.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from live_sim_lab_core_v1 import utc
from live_sim_lab_evolution_v1 import candidate_score

LOGGER = logging.getLogger("pricegauger.live_sim_lab.context")
ARM_NAMES = ("BASE", "MACRO", "GEO", "BOTH")
COHORT_SIZE = 5
COST_BPS = 5.0
MIN_SELECTION_BARS = 120
GEO_MAX_AGE_MINUTES = 15
MACRO_LOOKBACK_MINUTES = 20
MACRO_LOOKAHEAD_MINUTES = 15
CALENDAR_REFRESH_HOURS = 12
VERSION = "lsim-context-ablation-v1"
US_MACRO_TYPES = {
    "US_CPI", "US_PPI", "US_NFP", "US_PCE", "US_GDP",
    "FOMC_DECISION", "FOMC_MINUTES",
}


def ensure_context_lab_schema(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS lsim_ctx_candidates (
            instrument_id INTEGER NOT NULL,
            experiment_id TEXT NOT NULL,
            selected_at TEXT NOT NULL,
            selection_score REAL NOT NULL,
            selection_version TEXT NOT NULL,
            PRIMARY KEY(instrument_id,experiment_id)
        );
        CREATE TABLE IF NOT EXISTS lsim_ctx_arms (
            instrument_id INTEGER NOT NULL,
            experiment_id TEXT NOT NULL,
            arm TEXT NOT NULL,
            state_json TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(instrument_id,experiment_id,arm)
        );
        CREATE TABLE IF NOT EXISTS lsim_ctx_points (
            instrument_id INTEGER NOT NULL,
            experiment_id TEXT NOT NULL,
            arm TEXT NOT NULL,
            bar_time TEXT NOT NULL,
            equity REAL NOT NULL,
            exposure REAL NOT NULL,
            traded INTEGER NOT NULL,
            context_json TEXT NOT NULL,
            PRIMARY KEY(instrument_id,experiment_id,arm,bar_time)
        );
        CREATE TABLE IF NOT EXISTS lsim_ctx_macro_events (
            event_id TEXT PRIMARY KEY, scheduled_at TEXT NOT NULL,
            seen_at TEXT NOT NULL, event_type TEXT NOT NULL,
            importance TEXT NOT NULL, source TEXT NOT NULL,
            source_url TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS lsim_ctx_macro_times
            ON lsim_ctx_macro_events(scheduled_at);
        CREATE TABLE IF NOT EXISTS lsim_ctx_macro_refresh (
            id INTEGER PRIMARY KEY, checked_at TEXT NOT NULL,
            status TEXT NOT NULL, errors_json TEXT NOT NULL
        );
    """)


def refresh_macro_schedule(*, db_path="pricegauger.db", now=None,
                           loader=None):
    """Ingest known FUTURE official release schedules no more often than 12h.

    Source timestamps are recorded at observation time, not backfilled. Historical
    releases cannot be inserted retrospectively as if the lab knew them earlier.
    Network faults retain previous schedule but explicitly mark coverage partial.
    """
    from database import connect
    from macro_calendar import load_macro_calendar
    from live_sim_lab_store_v1 import ensure_lab_schema
    moment=utc(now or datetime.now(timezone.utc))
    ensure_lab_schema(db_path)
    with connect(db_path) as db:
        ensure_context_lab_schema(db)
        previous=db.execute(
            "SELECT checked_at,status FROM lsim_ctx_macro_refresh WHERE id=1"
        ).fetchone()
        if previous and (moment-utc(previous["checked_at"])).total_seconds() < CALENDAR_REFRESH_HOURS*3600:
            return "UNCHANGED"
    try:
        result=(loader or load_macro_calendar)(now=moment,horizon_days=21)
        errors=list(result.source_errors)
        status="PARTIAL" if errors else "READY"
        eligible=[e for e in result.events
                  if e.event_type in US_MACRO_TYPES and utc(e.scheduled_at) >= moment]
    except Exception as exc:
        status="UNAVAILABLE"
        eligible=[]
        errors=[type(exc).__name__]
    with connect(db_path) as db:
        ensure_context_lab_schema(db)
        for e in eligible:
            db.execute("""
                INSERT INTO lsim_ctx_macro_events(
                    event_id,scheduled_at,seen_at,event_type,importance,source,source_url)
                VALUES(?,?,?,?,?,?,?) ON CONFLICT(event_id) DO NOTHING
            """,(e.event_id,utc(e.scheduled_at).isoformat(),moment.isoformat(),
                 e.event_type,e.importance,e.source,e.source_url))
        db.execute("""
            INSERT INTO lsim_ctx_macro_refresh(id,checked_at,status,errors_json)
            VALUES(1,?,?,?) ON CONFLICT(id) DO UPDATE SET
                checked_at=excluded.checked_at,status=excluded.status,
                errors_json=excluded.errors_json
        """,(moment.isoformat(),status,json.dumps(errors)))
    return status


def freeze_five_candidates(db, *, instrument_id, states, bar_time):
    """Freeze the top five *eligible* baselines exactly once, prospectively.

    Selection itself is recorded; a losing experiment is still eligible.
    No survivor substitution after observing the outcomes of the four arms.
    """
    existing=db.execute("""
        SELECT experiment_id FROM lsim_ctx_candidates WHERE instrument_id=?
    """,(instrument_id,)).fetchall()
    if existing:
        return [str(x["experiment_id"]) for x in existing]
    active={r["experiment_id"] for r in db.execute("""
        SELECT experiment_id FROM lsim_experiments
        WHERE instrument_id=? AND status='ACTIVE'
    """,(instrument_id,)).fetchall()}
    eligible=[]
    for key,state in states.items():
        if key not in active or int((state.get("_evo") or {}).get("bars",0)) < MIN_SELECTION_BARS:
            continue
        score=candidate_score("RECENT",state,"RANGE")
        if score is not None:
            eligible.append((float(score),str(key)))
    if len(eligible)<COHORT_SIZE:
        return []
    ranked=sorted(eligible,key=lambda x:(-x[0],x[1]))[:COHORT_SIZE]
    for score,key in ranked:
        db.execute("""
            INSERT INTO lsim_ctx_candidates(
                instrument_id,experiment_id,selected_at,selection_score,selection_version)
            VALUES(?,?,?,?,?) ON CONFLICT(instrument_id,experiment_id) DO NOTHING
        """,(instrument_id,key,utc(bar_time).isoformat(),score,VERSION))
    return [key for _,key in ranked]


def _calendar_risk(db, *, bar_time):
    now=utc(bar_time)
    coverage=db.execute("""
        SELECT checked_at,status FROM lsim_ctx_macro_refresh WHERE id=1
    """).fetchone()
    if coverage is None or utc(coverage["checked_at"]) > now:
        return {"status":"MISSING","risk":False,"event_id":None}
    status=str(coverage["status"])
    if (now-utc(coverage["checked_at"])).total_seconds()>CALENDAR_REFRESH_HOURS*3600+3600:
        return {"status":"STALE","risk":False,"event_id":None}
    if status=="UNAVAILABLE":
        return {"status":"MISSING","risk":False,"event_id":None}
    rows=db.execute("""
        SELECT event_id,scheduled_at,seen_at,event_type,importance
        FROM lsim_ctx_macro_events
        WHERE scheduled_at>=? AND scheduled_at<=?
        ORDER BY scheduled_at,event_id LIMIT 50
    """,((now-timedelta(minutes=MACRO_LOOKBACK_MINUTES)).isoformat(),
         (now+timedelta(minutes=MACRO_LOOKAHEAD_MINUTES)).isoformat())).fetchall()
    for row in rows:
        # A scheduled release can be used only after the calendar was observed.
        if utc(row["seen_at"])<=now and row["event_type"] in US_MACRO_TYPES:
            return {"status":status,"risk":True,"event_id":row["event_id"]}
    return {"status":status,"risk":False,"event_id":None}


def _geopolitical_risk(db, *, bar_time):
    """Point-in-time News/Telegram AI context, no future as_of or publication."""
    now=utc(bar_time)
    try:
        rows=db.execute("""
            SELECT snapshot_id,as_of,recorded_at,payload_json
            FROM context_v2_snapshots
            WHERE scope_key='global'
            ORDER BY as_of DESC LIMIT 40
        """).fetchall()
    except Exception:  # Context is optional, never required to settle paper P/L.
        return {"status":"MISSING","risk":False,"snapshot_id":None}
    for row in rows:
        observed=utc(row["as_of"])
        recorded=utc(row["recorded_at"])
        if max(observed,recorded)>now:
            continue
        if (now-max(observed,recorded)).total_seconds() > GEO_MAX_AGE_MINUTES*60:
            continue
        payload=json.loads(row["payload_json"])
        if str(payload.get("freshness_status"))!="FRESH":
            continue
        coverage_end=payload.get("coverage_end")
        if coverage_end:
            data_end=utc(coverage_end)
            if data_end>now or (now-data_end).total_seconds()>GEO_MAX_AGE_MINUTES*60:
                continue
        # Defense against historical backfills and later-edited source material.
        refs=payload.get("evidence") or ()
        if any(utc(x.get("observed_at"))>now or
               (x.get("published_at") and utc(x["published_at"])>now)
               for x in refs):
            continue
        targets=payload.get("targets") or []
        maximum=0.0
        for t in targets:
            dimensions={d["name"]:d for d in t.get("dimensions") or []}
            confirmation=dimensions.get("confirmation_quality") or {}
            if float(confirmation.get("value",0))<0.55:
                continue
            risk=max(float(t.get("event_risk",0)),
                     max(0.0,float(dimensions.get("conflict_level",{}).get("value",0))),
                     max(0.0,float(dimensions.get("fear_level",{}).get("value",0))))
            # The macro calendar is not a direction forecast; this only measures
            # geopolitically stressed conditions in shared sources.
            confidence=min(float(t.get("confidence",0)),
                           float(confirmation.get("confidence",0)))
            if confidence>=0.6:
                maximum=max(maximum,risk*confidence)
        return {"status":"READY","risk":maximum>=0.55,
                "snapshot_id":row["snapshot_id"],"score":round(maximum,5)}
    return {"status":"MISSING","risk":False,"snapshot_id":None}


def context_for_bar(db, *, bar_time):
    return {"macro":_calendar_risk(db,bar_time=bar_time),
            "geo":_geopolitical_risk(db,bar_time=bar_time)}


def _empty_arm():
    return {"equity":10000.0,"peak":10000.0,"exposure":0.0,
            "pending":0.0,"last_close":None,"last_bar":None,
            "trades":0,"max_drawdown":0.0,"bars":0,
            "macro_known":0,"geo_known":0,"macro_triggered":0,
            "geo_triggered":0,"first_bar":None}


def _cap_target(base, arm, context):
    target=float(base)
    if arm in ("MACRO","BOTH") and context["macro"]["risk"]:
        target=0.0  # Test a blackout before/after major known US releases.
    if arm in ("GEO","BOTH") and context["geo"]["risk"]:
        target*=0.5  # Test halved exposure in verified news stress.
    return target


def settle_context_ablations(db, *, instrument_id, states, bar_time,
                             open_price, close_price):
    """Score existing five locked paired trials and persist one atomic paper ledger.

    Current bar is settled using target decided on the PREVIOUS CLOSED bar.
    Macro/geo evidence is read only for the NEXT bar. No backdating or trading.
    """
    current=utc(bar_time)
    parents=freeze_five_candidates(db,instrument_id=instrument_id,
                                  states=states,bar_time=current)
    if not parents:
        return 0
    registry=db.execute("""
        SELECT experiment_id,selected_at FROM lsim_ctx_candidates
        WHERE instrument_id=? ORDER BY experiment_id
    """,(instrument_id,)).fetchall()
    registered={r["experiment_id"]:utc(r["selected_at"]) for r in registry}
    if not any(current>stamp for stamp in registered.values()):
        return 0
    context=context_for_bar(db,bar_time=current)
    count=0
    for key,selected_at in registered.items():
        if current<=selected_at or key not in states or not states[key]:
            continue
        parent=states[key]
        parent_target=parent.get("pending")
        if parent_target is None:
            parent_target=parent.get("exposure",0.0)
        for arm in ARM_NAMES:
            previous=db.execute("""
                SELECT state_json FROM lsim_ctx_arms
                WHERE instrument_id=? AND experiment_id=? AND arm=?
            """,(instrument_id,key,arm)).fetchone()
            state=json.loads(previous["state_json"]) if previous else _empty_arm()
            if state.get("last_bar") is not None and utc(state["last_bar"])>=current:
                continue
            old_exp=float(state["exposure"])
            nav=float(state["equity"])
            op,cl=float(open_price),float(close_price)
            if min(op,cl)<=0:raise ValueError("invalid paper bar price")
            if state["last_close"] is not None:
                nav*=1+old_exp*(op/float(state["last_close"])-1)
            planned=float(state["pending"])
            change=abs(planned-old_exp)
            nav*=1-change*COST_BPS/10000.0
            nav*=1+planned*(cl/op-1)
            peak=max(float(state["peak"]),nav)
            state.update(equity=nav,peak=peak,exposure=planned,
                         pending=_cap_target(parent_target,arm,context),
                         last_close=cl,last_bar=current.isoformat(),
                         bars=int(state["bars"])+1,
                         max_drawdown=max(float(state["max_drawdown"]),
                                          1-nav/max(peak,1e-9)))
            if not state["first_bar"]:
                state["first_bar"]=current.isoformat()
            if change>1e-9:
                state["trades"]+=1
            state["macro_known"]+=int(context["macro"]["status"] in ("READY","PARTIAL"))
            state["geo_known"]+=int(context["geo"]["status"]=="READY")
            state["macro_triggered"]+=int(context["macro"]["risk"])
            state["geo_triggered"]+=int(context["geo"]["risk"])
            db.execute("""
                INSERT INTO lsim_ctx_arms(instrument_id,experiment_id,arm,state_json)
                VALUES(?,?,?,?) ON CONFLICT(instrument_id,experiment_id,arm)
                DO UPDATE SET state_json=excluded.state_json,updated_at=CURRENT_TIMESTAMP
            """,(instrument_id,key,arm,json.dumps(state)))
            if int(current.timestamp()//60)%5==0 or change>1e-9:
                db.execute("""
                    INSERT INTO lsim_ctx_points(
                        instrument_id,experiment_id,arm,bar_time,equity,exposure,traded,context_json)
                    VALUES(?,?,?,?,?,?,?,?)
                    ON CONFLICT(instrument_id,experiment_id,arm,bar_time) DO NOTHING
                """,(instrument_id,key,arm,current.isoformat(),nav,planned,
                     int(change>1e-9),json.dumps(context,sort_keys=True)))
            count+=1
    return count


def context_ablation_snapshot(*, db_path="pricegauger.db"):
    from database import connect
    from live_sim_lab_store_v1 import ensure_lab_schema
    ensure_lab_schema(db_path)
    with connect(db_path) as db:
        ensure_context_lab_schema(db)
        registry=[dict(x) for x in db.execute("""
            SELECT instrument_id,experiment_id,selected_at,selection_score
            FROM lsim_ctx_candidates ORDER BY selected_at,experiment_id
        """).fetchall()]
        arms=[dict(x) for x in db.execute("""
            SELECT instrument_id,experiment_id,arm,state_json
            FROM lsim_ctx_arms ORDER BY experiment_id,arm
        """).fetchall()]
        refresh=db.execute(
            "SELECT checked_at,status,errors_json FROM lsim_ctx_macro_refresh WHERE id=1"
        ).fetchone()
        recent=[dict(x) for x in db.execute("""
            SELECT instrument_id,experiment_id,arm,bar_time,equity,exposure,context_json
            FROM lsim_ctx_points ORDER BY bar_time DESC LIMIT 2000
        """).fetchall()]
    for arm in arms:
        arm.update(json.loads(arm.pop("state_json")))
    return registry, arms, (dict(refresh) if refresh else None), list(reversed(recent))
