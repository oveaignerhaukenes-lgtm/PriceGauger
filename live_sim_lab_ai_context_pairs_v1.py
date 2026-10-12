"""User-selected, forward-only paired LAB research for technical vs context AI.

Each enrolled base experiment gets three independently costed equal-start
paper tracks: BASE, TECH_AI, CONTEXT_AI. AI does not trade independently in this
module: it only gates the parent strategy's desired exposure (KEEP/HALF/FLAT).
Any missing/stale AI assessment falls back to BASE, never a fabricated edge.
All orders fill at NEXT canonical bar open; no Saxo or LIVE execution imports.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from database import connect
from live_sim_lab_core_v1 import utc

ARMS=("BASE","TECH_AI","CONTEXT_AI")
VERSION="lsim-ai-context-pairs-v1"
MAX_ENROLLED=6
MAX_POINTS=2400
REVIEW_TTL_SECONDS=1200


def ensure_pair_schema(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS lsim_ai_pair_enrollments (
            trial_id TEXT PRIMARY KEY,
            instrument_id INTEGER NOT NULL,
            experiment_id TEXT NOT NULL,
            selected_at TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('ACTIVE','STOPPED')),
            version TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS lsim_ai_pair_active
            ON lsim_ai_pair_enrollments(instrument_id,status);
        CREATE TABLE IF NOT EXISTS lsim_ai_pair_tracks (
            trial_id TEXT NOT NULL,arm TEXT NOT NULL,
            state_json TEXT NOT NULL,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(trial_id,arm)
        );
        CREATE TABLE IF NOT EXISTS lsim_ai_pair_points (
            trial_id TEXT NOT NULL,arm TEXT NOT NULL,bar_time TEXT NOT NULL,
            equity REAL NOT NULL,exposure REAL NOT NULL,traded INTEGER NOT NULL,
            decision TEXT NOT NULL,
            PRIMARY KEY(trial_id,arm,bar_time)
        );
        CREATE TABLE IF NOT EXISTS lsim_ai_pair_reviews (
            trial_id TEXT NOT NULL,arm TEXT NOT NULL,source_bar TEXT NOT NULL,
            requested_at TEXT NOT NULL,completed_at TEXT,
            status TEXT NOT NULL,model TEXT NOT NULL,
            action TEXT NOT NULL,confidence REAL,reason TEXT NOT NULL,
            evidence_json TEXT NOT NULL,coverage_json TEXT NOT NULL,
            PRIMARY KEY(trial_id,arm,source_bar)
        );
        CREATE INDEX IF NOT EXISTS lsim_ai_pair_review_latest
            ON lsim_ai_pair_reviews(trial_id,arm,completed_at);
    """)


def available_parents(*,db_path="pricegauger.db"):
    from live_sim_lab_store_v1 import ensure_lab_schema
    ensure_lab_schema(db_path)
    with connect(db_path) as db:
        return [dict(row) for row in db.execute("""
            SELECT experiment_id,instrument_id,market_name,family,signal_tf,
                   regime_tf,modifier,max_exposure,cost_bps,status
            FROM lsim_experiments WHERE status='ACTIVE'
            ORDER BY instrument_id,family,signal_tf,regime_tf,modifier,experiment_id
        """).fetchall()]


def enroll_pairs(experiment_ids,*,db_path="pricegauger.db",now=None):
    """Explicit operator-only research selection; no LIVE or trading mutations.

    Changed cohorts start fresh *after* enrollment, never retroactive P/L.
    Stopped cohorts remain immutable/auditable, reselecting creates a new trial.
    """
    chosen=list(dict.fromkeys(str(x) for x in experiment_ids))
    if len(chosen)>MAX_ENROLLED:
        raise ValueError("At most six paired research strategies")
    moment=utc(now or datetime.now(timezone.utc)).isoformat()
    from live_sim_lab_store_v1 import ensure_lab_schema
    ensure_lab_schema(db_path)
    with connect(db_path) as db:
        ensure_pair_schema(db)
        if chosen:
            placeholders=",".join("?" for _ in chosen)
            verified=db.execute(
                "SELECT experiment_id,instrument_id FROM lsim_experiments "
                "WHERE status='ACTIVE' AND experiment_id IN ("+placeholders+")",
                chosen).fetchall()
        else:
            verified=[]
        found={x["experiment_id"]:int(x["instrument_id"]) for x in verified}
        if len(found)!=len(chosen):
            raise ValueError("Selected lab experiment is unknown/inactive")
        active=db.execute("""
            SELECT trial_id,experiment_id FROM lsim_ai_pair_enrollments
            WHERE status='ACTIVE'
        """).fetchall()
        existing={x["experiment_id"]:x["trial_id"] for x in active}
        for entry in active:
            if entry["experiment_id"] not in found:
                db.execute("""
                    UPDATE lsim_ai_pair_enrollments SET status='STOPPED'
                    WHERE trial_id=?
                """,(entry["trial_id"],))
        created=0
        for key in chosen:
            if key in existing:
                continue
            db.execute("""
                INSERT INTO lsim_ai_pair_enrollments(
                    trial_id,instrument_id,experiment_id,selected_at,status,version)
                VALUES(?,?,?,?,'ACTIVE',?)
            """,(uuid.uuid4().hex,found[key],key,moment,VERSION))
            created+=1
    return created


def _empty():
    return {"equity":10000.0,"peak":10000.0,"max_drawdown":0.0,
            "exposure":0.0,"pending":0.0,"last_close":None,
            "last_bar":None,"first_bar":None,
            "bars":0,"trades":0,"costs":0.0,
            "ai_applied":0,"ai_missing":0,"ai_half":0,"ai_flat":0,
            "last_reason":"WAITING_FIRST_BAR"}


def _known_review(db,trial_id,arm,*,as_of):
    """Only use model output known before this bar CLOSED.

    Returned proposal influences NEXT bar's open, never a prior or already-open
    bar. A future record cannot alter earlier replayed bar state.
    """
    rows=db.execute("""
        SELECT completed_at,status,action FROM lsim_ai_pair_reviews
        WHERE trial_id=? AND arm=? AND status='READY'
          AND completed_at<=?
        ORDER BY completed_at DESC LIMIT 1
    """,(trial_id,arm,utc(as_of).isoformat())).fetchall()
    if not rows:
        return None
    chosen=rows[0]
    age=(utc(as_of)-utc(chosen["completed_at"])).total_seconds()
    if age<0 or age>REVIEW_TTL_SECONDS:
        return None
    return str(chosen["action"])


def gate_parent_target(parent,action):
    """No AI can reverse or increase the underlying base strategy position."""
    target=float(parent)
    return (0.0 if action=="FLAT" else
            round(target*0.5,8) if action=="HALF" else target)


def settle_selected_pairs(db,*,instrument_id,states,bar_time,
                          open_price,close_price):
    """Atomic with the canonical LAB bar cursor and base strategy settlement."""
    ensure_pair_schema(db)
    moment=utc(bar_time)
    bar_close=moment+timedelta(minutes=1)
    active=db.execute("""
        SELECT trial_id,experiment_id,selected_at
        FROM lsim_ai_pair_enrollments
        WHERE instrument_id=? AND status='ACTIVE'
        ORDER BY trial_id
    """,(instrument_id,)).fetchall()
    if not active:
        return 0
    n=0
    op,cl=float(open_price),float(close_price)
    if not min(op,cl)>0:
        raise ValueError("nonpositive paper bar")
    for parent in active:
        trial=parent["trial_id"]
        key=parent["experiment_id"]
        # Selected_at is wall time, not fictional backtest start.
        if moment<=utc(parent["selected_at"]) or key not in states or not states[key]:
            continue
        cfg_row=db.execute(
            "SELECT cost_bps,max_exposure FROM lsim_experiments "
            "WHERE experiment_id=? AND status='ACTIVE'",(key,)).fetchone()
        if cfg_row is None:
            continue
        cost_bps=float(cfg_row["cost_bps"])
        parent_target=float(states[key].get("pending",states[key].get("exposure",0)))
        for arm in ARMS:
            row=db.execute("""
                SELECT state_json FROM lsim_ai_pair_tracks
                WHERE trial_id=? AND arm=?
            """,(trial,arm)).fetchone()
            state=json.loads(row["state_json"]) if row else _empty()
            if state["last_bar"] and utc(state["last_bar"])>=moment:
                continue
            old=float(state["exposure"])
            desired=float(state["pending"])
            nav=float(state["equity"])
            if state["last_close"] is not None:
                nav*=1+old*(op/float(state["last_close"])-1)
            turnover=abs(desired-old)
            cost=nav*turnover*cost_bps/10000
            nav-=cost
            nav*=1+desired*(cl/op-1)
            action=(_known_review(db,trial,arm,as_of=bar_close)
                    if arm!="BASE" else "KEEP")
            new_target=gate_parent_target(parent_target,action)
            peak=max(float(state["peak"]),nav)
            state.update(
                equity=nav,peak=peak,exposure=desired,pending=new_target,
                max_drawdown=max(float(state["max_drawdown"]),1-nav/max(1e-9,peak)),
                last_close=cl,last_bar=moment.isoformat(),
                first_bar=state["first_bar"] or moment.isoformat(),
                bars=int(state["bars"])+1,
                trades=int(state["trades"])+int(turnover>1e-9),
                costs=float(state["costs"])+cost,
                ai_applied=int(state["ai_applied"])+int(
                    arm!="BASE" and action in ("HALF","FLAT")),
                ai_missing=int(state["ai_missing"])+int(
                    arm!="BASE" and action is None),
                ai_half=int(state["ai_half"])+int(arm!="BASE" and action=="HALF"),
                ai_flat=int(state["ai_flat"])+int(arm!="BASE" and action=="FLAT"),
                last_reason=(action or "NO_RECENT_AI") if arm!="BASE" else "BASE",
            )
            db.execute("""
                INSERT INTO lsim_ai_pair_tracks(trial_id,arm,state_json)
                VALUES(?,?,?) ON CONFLICT(trial_id,arm) DO UPDATE
                SET state_json=excluded.state_json,updated_at=CURRENT_TIMESTAMP
            """,(trial,arm,json.dumps(state)))
            # Same timestamps for each matched arm.
            if int(moment.timestamp()//60)%5==0 or turnover>1e-9:
                db.execute("""
                    INSERT INTO lsim_ai_pair_points(
                        trial_id,arm,bar_time,equity,exposure,traded,decision)
                    VALUES(?,?,?,?,?,?,?)
                    ON CONFLICT(trial_id,arm,bar_time) DO NOTHING
                """,(trial,arm,moment.isoformat(),nav,desired,
                     int(turnover>1e-9),state["last_reason"]))
            n+=1
    return n


def pair_snapshot(*,db_path="pricegauger.db",limit=MAX_POINTS):
    with connect(db_path) as db:
        ensure_pair_schema(db)
        cohorts=[dict(x) for x in db.execute("""
            SELECT e.trial_id,e.instrument_id,e.experiment_id,e.selected_at,e.status,
                   l.family,l.signal_tf,l.regime_tf,l.modifier,l.max_exposure,
                   l.market_name
            FROM lsim_ai_pair_enrollments e
            JOIN lsim_experiments l ON l.experiment_id=e.experiment_id
            WHERE e.status='ACTIVE' ORDER BY e.selected_at,e.experiment_id
        """).fetchall()]
        tracks=[dict(x) for x in db.execute("""
            SELECT t.trial_id,t.arm,t.state_json FROM lsim_ai_pair_tracks t
            JOIN lsim_ai_pair_enrollments e ON e.trial_id=t.trial_id
            WHERE e.status='ACTIVE' ORDER BY t.trial_id,t.arm
        """).fetchall()]
        points=[dict(x) for x in db.execute("""
            SELECT p.trial_id,p.arm,p.bar_time,p.equity,p.exposure,p.traded,
                   p.decision FROM lsim_ai_pair_points p
            JOIN lsim_ai_pair_enrollments e ON e.trial_id=p.trial_id
            WHERE e.status='ACTIVE'
            ORDER BY p.bar_time DESC LIMIT ?
        """,(max(1,min(10000,int(limit))),)).fetchall()]
        reviews=[dict(x) for x in db.execute("""
            SELECT r.trial_id,r.arm,r.source_bar,r.requested_at,r.completed_at,
                   r.status,r.action,r.confidence,r.reason,r.coverage_json
            FROM lsim_ai_pair_reviews r
            JOIN lsim_ai_pair_enrollments e ON e.trial_id=r.trial_id
            WHERE e.status='ACTIVE'
            ORDER BY r.requested_at DESC LIMIT 80
        """).fetchall()]
    for t in tracks:
        t.update(json.loads(t.pop("state_json")))
    for r in reviews:
        r["coverage"]=json.loads(r.pop("coverage_json"))
    return cohorts,tracks,list(reversed(points)),reviews
