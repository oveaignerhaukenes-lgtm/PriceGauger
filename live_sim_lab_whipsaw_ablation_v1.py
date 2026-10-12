"""Prospective paired whipsaw policy ablation over existing Lab research parents.

Four shadow-only tracks: BASE, PAUSE, REDUCE, FLAT. The detector is the same
closed-bar WHIPSAW tag used by Live-Sim Lab's existing technical_regime().
Never invokes LIVE runtime or Saxo, never modifies strategy configs.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from live_sim_lab_core_v1 import utc
from live_sim_lab_evolution_v1 import candidate_score

ARMS = ("BASE", "PAUSE", "REDUCE", "FLAT")
COHORT = 5
MIN_PARENT_BARS = 120
CLEAR_BARS = 3
FLAT_COOLDOWN_BARS = 3
EXECUTION_COST_BPS = 5.0
VERSION = "whipsaw-paired-v1"


def ensure_whipsaw_schema(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS lsim_whip_parents(
            instrument_id INTEGER NOT NULL, experiment_id TEXT NOT NULL,
            selected_at TEXT NOT NULL, selection_score REAL NOT NULL,
            study_version TEXT NOT NULL,
            PRIMARY KEY(instrument_id, experiment_id)
        );
        CREATE TABLE IF NOT EXISTS lsim_whip_tracks(
            instrument_id INTEGER NOT NULL, experiment_id TEXT NOT NULL,
            arm TEXT NOT NULL, state_json TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(instrument_id, experiment_id, arm)
        );
        CREATE TABLE IF NOT EXISTS lsim_whip_points(
            instrument_id INTEGER NOT NULL, experiment_id TEXT NOT NULL,
            arm TEXT NOT NULL, bar_time TEXT NOT NULL,
            equity REAL NOT NULL, exposure REAL NOT NULL, traded INTEGER NOT NULL,
            raw_whipsaw INTEGER NOT NULL, effective_whipsaw INTEGER NOT NULL,
            signal_change_count INTEGER, efficiency REAL, decision TEXT NOT NULL,
            PRIMARY KEY(instrument_id, experiment_id, arm, bar_time)
        );
    """)


def freeze_whipsaw_cohort(db, *, instrument_id, parent_states, stamp):
    """Only choose five existing unmodified research parents, once, at close."""
    existing=db.execute("""
        SELECT experiment_id FROM lsim_whip_parents
        WHERE instrument_id=? ORDER BY experiment_id
    """, (instrument_id,)).fetchall()
    if existing:
        return [x["experiment_id"] for x in existing]
    rows=db.execute("""
        SELECT experiment_id,config_json
        FROM lsim_experiments
        WHERE instrument_id=? AND status='ACTIVE'
    """,(instrument_id,)).fetchall()
    eligible=[]
    for row in rows:
        key=str(row["experiment_id"])
        config=json.loads(row["config_json"])
        if config.get("modifier")!="none":
            continue  # do not evaluate whipsaw applied on top of whipsaw
        parent=parent_states.get(key) or {}
        if int((parent.get("_evo") or {}).get("bars",0))<MIN_PARENT_BARS:
            continue
        score=candidate_score("RECENT",parent,"RANGE")
        if score is not None:
            eligible.append((float(score),key))
    if len(eligible)<COHORT:
        return []
    chosen=sorted(eligible,key=lambda x:(-x[0],x[1]))[:COHORT]
    for score,key in chosen:
        db.execute("""
            INSERT INTO lsim_whip_parents(
                instrument_id,experiment_id,selected_at,selection_score,study_version)
            VALUES(?,?,?,?,?) ON CONFLICT(instrument_id,experiment_id) DO NOTHING
        """,(instrument_id,key,utc(stamp).isoformat(),score,VERSION))
    return [key for _,key in chosen]


def detector_evidence(features):
    """Reuse canonical Live-Sim WHIPSAW tag; compute transparent diagnostics."""
    values=list(features.get("returns") or [])[-12:]
    if len(values)<12:
        return {"raw":False,"changes":None,"efficiency":None}
    changes=sum(a*b<0 for a,b in zip(values,values[1:]))
    efficiency=abs(sum(values))/max(1e-12,sum(abs(v) for v in values))
    return {
        "raw":"WHIPSAW" in (features.get("tags") or ()),
        "changes":changes,"efficiency":round(efficiency,6),
    }


def _initial_track():
    return {
        "equity":10000.0, "peak":10000.0, "max_drawdown":0.0,
        "exposure":0.0, "pending":0.0, "last_close":None,"last_bar":None,
        "first_bar":None,"bars":0, "trades":0,"transaction_cost_nok":0.0,
        "raw_whipsaw_bars":0, "effective_whipsaw_bars":0,
        "activation_count":0, "blocked_increases":0,"forced_reductions":0,
        "forced_flats":0, "active":False,"quiet_bars":0,
        "cooldown_remaining":0,
    }


def _updated_detector(state, *, raw):
    """Activate immediately; require three consecutive quiet CLOSED bars to clear."""
    if raw:
        activated=not state["active"]
        state["active"]=True
        state["quiet_bars"]=0
        if activated:
            state["activation_count"]+=1
            state["cooldown_remaining"]=FLAT_COOLDOWN_BARS
    elif state["active"]:
        state["quiet_bars"]+=1
        if state["quiet_bars"]>=CLEAR_BARS:
            state["active"]=False
            state["quiet_bars"]=0
    if not raw and int(state["cooldown_remaining"])>0:
        state["cooldown_remaining"]-=1
    return bool(state["active"] or state["cooldown_remaining"]>0)


def select_policy_target(*, arm, parent_target, current_exposure, config,
                         active, forbidden):
    """Pure independently measurable response to a detector's closed-bar state."""
    target=float(parent_target)
    current=float(current_exposure)
    if arm=="BASE" or (not active and not forbidden):
        return target,"PASS"
    if arm=="FLAT":
        if abs(target)>1e-9 or abs(current)>1e-9:
            return 0.0,"WHIPSAW_FLAT_COOLDOWN"
        return 0.0,"WHIPSAW_FLAT_IDLE"
    if not active:  # For PAUSE/REDUCE, cooldown alone must not change behavior.
        return target,"PASS"
    if abs(current)>1e-9 and target*current < -1e-10:
        return 0.0,"WHIPSAW_OPPOSITE_FIRST_FLAT"
    if arm=="PAUSE":
        if abs(target)>abs(current)+1e-9:
            return current,"WHIPSAW_PAUSE_BUILD"
        return target,"PASS"
    if arm=="REDUCE":
        if abs(current)<1e-9:
            if abs(target)>1e-9:
                return 0.0,"WHIPSAW_REDUCE_NO_NEW_ENTRY"
            return 0.0,"PASS"
        limit=0.5*float(config["max_exposure"])
        smaller=min(abs(target),abs(current),limit)
        adjusted=(1 if current>0 else -1)*smaller
        return adjusted,("WHIPSAW_REDUCE" if abs(adjusted)<abs(current)-1e-9
                         else "WHIPSAW_HOLD_OR_EXIT")
    raise ValueError(f"unexpected ablation arm: {arm}")


def settle_whipsaw_ablation(db, *, instrument_id, parent_states, features,
                            bar_time, open_price, close_price):
    """All fills at NEXT bar open, after earlier closed-bar target; no replay.

    Paired streams have identical provenance, cost model and start capital.
    Only a completed bar can alter next-bar position. Updates are transactional.
    """
    moment=utc(bar_time)
    freeze_whipsaw_cohort(db,instrument_id=instrument_id,
                          parent_states=parent_states,stamp=moment)
    selected=db.execute("""
        SELECT experiment_id,selected_at FROM lsim_whip_parents
        WHERE instrument_id=? ORDER BY experiment_id
    """,(instrument_id,)).fetchall()
    if not selected:
        return 0
    evidence=detector_evidence(features)
    price_open,price_close=float(open_price),float(close_price)
    if min(price_open,price_close)<=0:
        raise ValueError("nonpositive research candle")
    complete=0
    for parent in selected:
        key=parent["experiment_id"]
        if moment<=utc(parent["selected_at"]) or key not in parent_states:
            continue
        original=parent_states[key]
        config_row=db.execute(
            "SELECT config_json FROM lsim_experiments WHERE experiment_id=?",
            (key,)).fetchone()
        if config_row is None:
            continue
        cfg=json.loads(config_row["config_json"])
        if cfg.get("modifier")!="none":
            continue
        reference=original.get("pending")
        if reference is None:
            reference=original.get("exposure",0)
        for arm in ARMS:
            row=db.execute("""
                SELECT state_json FROM lsim_whip_tracks
                WHERE instrument_id=? AND experiment_id=? AND arm=?
            """,(instrument_id,key,arm)).fetchone()
            state=json.loads(row["state_json"]) if row else _initial_track()
            if state["last_bar"] is not None and utc(state["last_bar"])>=moment:
                continue
            equity=float(state["equity"])
            before=float(state["exposure"])
            if state["last_close"] is not None:
                equity*=1+before*(price_open/float(state["last_close"])-1)
            pending=float(state["pending"])
            turnover=abs(pending-before)
            fee=equity*turnover*EXECUTION_COST_BPS/10000
            equity-=fee
            equity*=1+pending*(price_close/price_open-1)
            peak=max(float(state["peak"]),equity)
            if arm!="BASE":
                forbidden=_updated_detector(state,raw=evidence["raw"])
                active=bool(state["active"])
            else:
                active=False
                forbidden=False
            proposed,reason=select_policy_target(
                arm=arm,parent_target=reference,current_exposure=pending,
                config=cfg,active=active,forbidden=forbidden,
            )
            state.update(
                equity=equity,peak=peak,
                max_drawdown=max(float(state["max_drawdown"]),1-equity/max(peak,1e-9)),
                exposure=pending,pending=proposed,
                last_close=price_close,last_bar=moment.isoformat(),
                first_bar=state["first_bar"] or moment.isoformat(),
                bars=int(state["bars"])+1,
                trades=int(state["trades"])+int(turnover>1e-9),
                transaction_cost_nok=float(state["transaction_cost_nok"])+fee,
                raw_whipsaw_bars=int(state["raw_whipsaw_bars"])+int(evidence["raw"]),
                effective_whipsaw_bars=int(state["effective_whipsaw_bars"])+int(active),
                blocked_increases=int(state["blocked_increases"])+int(
                    reason in ("WHIPSAW_PAUSE_BUILD","WHIPSAW_REDUCE_NO_NEW_ENTRY")),
                forced_reductions=int(state["forced_reductions"])+int(
                    reason=="WHIPSAW_REDUCE"),
                forced_flats=int(state["forced_flats"])+int(
                    reason=="WHIPSAW_FLAT_COOLDOWN" and
                    (abs(pending)>1e-9 or abs(proposed)>1e-9)),
            )
            db.execute("""
                INSERT INTO lsim_whip_tracks(
                    instrument_id,experiment_id,arm,state_json)
                VALUES(?,?,?,?) ON CONFLICT(instrument_id,experiment_id,arm)
                DO UPDATE SET state_json=excluded.state_json,updated_at=CURRENT_TIMESTAMP
            """,(instrument_id,key,arm,json.dumps(state)))
            if int(moment.timestamp()//60)%5==0 or turnover>1e-9:
                db.execute("""
                    INSERT INTO lsim_whip_points(
                        instrument_id,experiment_id,arm,bar_time,equity,exposure,
                        traded,raw_whipsaw,effective_whipsaw,
                        signal_change_count,efficiency,decision)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(instrument_id,experiment_id,arm,bar_time) DO NOTHING
                """,(instrument_id,key,arm,moment.isoformat(),equity,pending,
                     int(turnover>1e-9),int(evidence["raw"]),int(active),
                     evidence["changes"],evidence["efficiency"],reason))
            complete+=1
    return complete


def whipsaw_snapshot(*, db_path="pricegauger.db"):
    from database import connect
    from live_sim_lab_store_v1 import ensure_lab_schema
    ensure_lab_schema(db_path)
    with connect(db_path) as db:
        ensure_whipsaw_schema(db)
        selected=[dict(x) for x in db.execute("""
            SELECT instrument_id,experiment_id,selected_at,selection_score
            FROM lsim_whip_parents ORDER BY instrument_id,selection_score DESC
        """).fetchall()]
        tracks=[dict(x) for x in db.execute("""
            SELECT instrument_id,experiment_id,arm,state_json
            FROM lsim_whip_tracks ORDER BY experiment_id,arm
        """).fetchall()]
        points=[dict(x) for x in db.execute("""
            SELECT instrument_id,experiment_id,arm,bar_time,equity,exposure,
                   traded,raw_whipsaw,effective_whipsaw,decision
            FROM lsim_whip_points ORDER BY bar_time DESC LIMIT 1600
        """).fetchall()]
    for row in tracks:
        row.update(json.loads(row.pop("state_json")))
    return selected,tracks,list(reversed(points))
