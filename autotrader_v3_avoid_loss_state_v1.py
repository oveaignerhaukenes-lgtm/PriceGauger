"""Durable Avoid Loss risk memory and immutable entry margin anchors.

All functions mutate ONLY the dedicated research tables, NEVER Saxo accounts
or V3 LIVE authorization. A margin anchor can be registered only against an
externally confirmed durable V3 OPEN; adoption of an old broker position may
NOT synthesize an opening margin. The caller must validate request/position
provenance before registration; current module is not a LIVE adapter.
"""
from __future__ import annotations

from datetime import datetime, timezone
from json import dumps, loads
from math import isfinite

from autotrader_v3_avoid_loss_v1 import (
    AvoidLossStateV1, ConfirmedPositionV1, _utc,
)
from database import connect


def ensure_avoid_loss_research_schema_v1(*,db_path="pricegauger.db"):
    with connect(db_path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS autotrader_v3_avoid_loss_anchor_v1 (
            trader_id TEXT PRIMARY KEY,
            position_key TEXT NOT NULL,
            account_id TEXT NOT NULL,
            uic INTEGER NOT NULL,
            asset_type TEXT NOT NULL,
            position_token TEXT NOT NULL,
            signed_amount DOUBLE PRECISION NOT NULL,
            frozen_margin_nok DOUBLE PRECISION NOT NULL,
            reconciled_open_request_key TEXT NOT NULL,
            confirmed_order_id TEXT NOT NULL,
            anchored_at TEXT NOT NULL
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS autotrader_v3_avoid_loss_risk_v1 (
            trader_id TEXT PRIMARY KEY,
            position_key TEXT NOT NULL,
            peak_pct DOUBLE PRECISION NOT NULL,
            trailing_armed INTEGER NOT NULL,
            exit_pending INTEGER NOT NULL,
            exit_reason TEXT,
            last_sample_at TEXT,
            updated_at TEXT NOT NULL
        )""")


def _position_key(position:ConfirmedPositionV1)->str:
    return dumps(position.key,separators=(",",":"))


def register_confirmed_entry_anchor_v1(
    *,trader_id:str,position:ConfirmedPositionV1,
    reconciled_open_request_key:str,confirmed_order_id:str,
    confirmed_at:datetime,db_path="pricegauger.db",
)->bool:
    """Idempotently persist a *confirmed* entry anchor; never reprice it.

    This cannot itself prove broker confirmation: a future V3 integration must
    call it ONLY after matching the durable order ledger with exact broker
    inventory and broker order history. Any conflicting replacement fails.
    """
    if not all((str(trader_id).strip(),
                str(reconciled_open_request_key).strip(),
                str(confirmed_order_id).strip())):
        raise ValueError("confirmed order and instance identifiers required")
    at=_utc(confirmed_at).isoformat()
    key=_position_key(position)
    ensure_avoid_loss_research_schema_v1(db_path=db_path)
    with connect(db_path) as db:
        existing=db.execute(
            "SELECT position_key,frozen_margin_nok,reconciled_open_request_key,confirmed_order_id "
            "FROM autotrader_v3_avoid_loss_anchor_v1 WHERE trader_id=?",
            (trader_id,),
        ).fetchone()
        if existing is not None:
            if (str(existing["position_key"])!=key
                or abs(float(existing["frozen_margin_nok"])-position.entry_margin_nok)>1e-9
                or str(existing["reconciled_open_request_key"])!=reconciled_open_request_key
                or str(existing["confirmed_order_id"])!=confirmed_order_id):
                raise ValueError("immutable live-position anchor conflict; explicit broker FLAT required")
            return False
        db.execute("""INSERT INTO autotrader_v3_avoid_loss_anchor_v1 (
            trader_id,position_key,account_id,uic,asset_type,position_token,
            signed_amount,frozen_margin_nok,reconciled_open_request_key,
            confirmed_order_id,anchored_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",(
            trader_id,key,position.account_id,position.uic,position.asset_type,
            position.position_token,position.signed_amount,position.entry_margin_nok,
            reconciled_open_request_key,confirmed_order_id,at))
    return True


def load_confirmed_entry_anchor_v1(*,trader_id:str,db_path="pricegauger.db"):
    ensure_avoid_loss_research_schema_v1(db_path=db_path)
    with connect(db_path) as db:
        row=db.execute(
            "SELECT account_id,uic,asset_type,position_token,signed_amount,frozen_margin_nok "
            "FROM autotrader_v3_avoid_loss_anchor_v1 WHERE trader_id=?",
            (trader_id,),
        ).fetchone()
    if row is None:
        return None
    return ConfirmedPositionV1(
        account_id=str(row["account_id"]),uic=int(row["uic"]),
        asset_type=str(row["asset_type"]),position_token=str(row["position_token"]),
        signed_amount=float(row["signed_amount"]),
        entry_margin_nok=float(row["frozen_margin_nok"]),
    )


def save_risk_state_v1(*,trader_id:str,state:AvoidLossStateV1,db_path="pricegauger.db"):
    """Maintain monotone high water, monotone event time and sticky CLOSE.

    Reject outdated writes instead of allowing a delayed risk-loop result to
    erase a prior confirmed stop. The current implementation is sequential;
    integrating LIVE requires a serialized transaction/instance lease.
    """
    ensure_avoid_loss_research_schema_v1(db_path=db_path)
    anchor=load_confirmed_entry_anchor_v1(trader_id=trader_id,db_path=db_path)
    if anchor is None or state.position_key!=anchor.key:
        raise ValueError("risk state lacks matching confirmed entry anchor")
    key=_position_key(anchor)
    stamp=_utc(state.last_sample_at).isoformat() if state.last_sample_at else None
    now=datetime.now(timezone.utc).isoformat()
    with connect(db_path) as db:
        row=db.execute(
            "SELECT last_sample_at,peak_pct,trailing_armed,exit_pending,exit_reason "
            "FROM autotrader_v3_avoid_loss_risk_v1 WHERE trader_id=?",
            (trader_id,),
        ).fetchone()
        if row is not None:
            old=row["last_sample_at"]
            if (old is not None and (stamp is None or stamp<str(old))
                or state.peak_pct+1e-9<float(row["peak_pct"])
                or bool(row["trailing_armed"]) and not state.trailing_armed
                or bool(row["exit_pending"]) and not state.exit_pending):
                raise ValueError("cannot roll back HWM, risk timestamp, or CLOSE latch")
        db.execute("""INSERT INTO autotrader_v3_avoid_loss_risk_v1(
            trader_id,position_key,peak_pct,trailing_armed,exit_pending,
            exit_reason,last_sample_at,updated_at
        ) VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(trader_id) DO UPDATE SET
            position_key=excluded.position_key,
            peak_pct=excluded.peak_pct,
            trailing_armed=excluded.trailing_armed,
            exit_pending=excluded.exit_pending,
            exit_reason=excluded.exit_reason,
            last_sample_at=excluded.last_sample_at,
            updated_at=excluded.updated_at""",(
            trader_id,key,state.peak_pct,int(state.trailing_armed),
            int(state.exit_pending),state.exit_reason,stamp,now))


def load_risk_state_v1(*,trader_id:str,db_path="pricegauger.db"):
    ensure_avoid_loss_research_schema_v1(db_path=db_path)
    anchor=load_confirmed_entry_anchor_v1(trader_id=trader_id,db_path=db_path)
    if anchor is None:
        return None
    with connect(db_path) as db:
        row=db.execute(
            "SELECT position_key,peak_pct,trailing_armed,exit_pending,"
            "exit_reason,last_sample_at FROM autotrader_v3_avoid_loss_risk_v1 "
            "WHERE trader_id=?",(trader_id,)
        ).fetchone()
    if row is None:
        return None
    if str(row["position_key"])!=_position_key(anchor):
        raise ValueError("stale risk state for different broker position")
    stamp=row["last_sample_at"]
    return AvoidLossStateV1(
        position_key=anchor.key,peak_pct=float(row["peak_pct"]),
        trailing_armed=bool(row["trailing_armed"]),
        exit_pending=bool(row["exit_pending"]),
        exit_reason=row["exit_reason"],
        last_sample_at=datetime.fromisoformat(stamp) if stamp else None,
    )


def retire_confirmed_flat_v1(*,trader_id:str,broker_exact_flat:bool,
                              db_path="pricegauger.db")->bool:
    """Never retire after order SUBMITTED; only after Saxo FLAT reconciliation.

    A future LIVE worker must also record last exit signal/time separately so
    re-entry waits for a NEW completed MACD 2m bar.
    """
    if broker_exact_flat is not True:
        raise ValueError("broker-confirmed exact FLAT required to retire stop")
    ensure_avoid_loss_research_schema_v1(db_path=db_path)
    with connect(db_path) as db:
        db.execute("DELETE FROM autotrader_v3_avoid_loss_risk_v1 WHERE trader_id=?",
                   (trader_id,))
        result=db.execute(
            "DELETE FROM autotrader_v3_avoid_loss_anchor_v1 WHERE trader_id=?",
            (trader_id,))
        # Retire the previous lifecycle's preflight stages only AFTER Saxo FLAT.
        db.execute("""CREATE TABLE IF NOT EXISTS autotrader_v3_avoid_loss_preflight_v1 (
           request_key TEXT PRIMARY KEY, trader_id TEXT NOT NULL,
           account_id TEXT NOT NULL, uic INTEGER NOT NULL,
           asset_type TEXT NOT NULL, signed_amount DOUBLE PRECISION NOT NULL,
           initial_margin_nok DOUBLE PRECISION NOT NULL, created_at TEXT NOT NULL
        )""")
        db.execute("DELETE FROM autotrader_v3_avoid_loss_preflight_v1 WHERE trader_id=?",
                   (trader_id,))
    return result.rowcount>0



def stage_entry_preflight_v1(*,trader_id:str,request_key:str,
                             margin_nok:float,account_id:str,uic:int,
                             asset_type:str,signed_amount:float,
                             db_path="pricegauger.db")->None:
    """Persist precheck margin BEFORE a V3 durable OPEN request is submitted.

    The stage is inert until the exact OPEN request is RECONCILED and Saxo
    confirms the individual PositionId, direction and quantity. No guessed
    entries and no modifications to existing V3 order-guard records.
    """
    if not all([str(trader_id),str(request_key),str(account_id),str(asset_type)]):
        raise ValueError("entry stage identity missing")
    if (not isfinite(float(margin_nok)) or margin_nok<=0
        or not isfinite(float(signed_amount)) or signed_amount==0):
        raise ValueError("invalid Saxo precheck margin or requested size")
    ensure_avoid_loss_research_schema_v1(db_path=db_path)
    with connect(db_path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS autotrader_v3_avoid_loss_preflight_v1 (
           request_key TEXT PRIMARY KEY,
           trader_id TEXT NOT NULL, account_id TEXT NOT NULL,
           uic INTEGER NOT NULL, asset_type TEXT NOT NULL,
           signed_amount DOUBLE PRECISION NOT NULL,
           initial_margin_nok DOUBLE PRECISION NOT NULL,
           created_at TEXT NOT NULL
        )""")
        current=db.execute(
            "SELECT trader_id,account_id,uic,asset_type,signed_amount,initial_margin_nok "
            "FROM autotrader_v3_avoid_loss_preflight_v1 WHERE request_key=?",
            (request_key,)).fetchone()
        if current is not None:
            if (str(current["trader_id"])!=trader_id or
                str(current["account_id"])!=account_id or
                int(current["uic"])!=int(uic) or
                str(current["asset_type"])!=asset_type or
                abs(float(current["signed_amount"])-signed_amount)>1e-9 or
                abs(float(current["initial_margin_nok"])-margin_nok)>1e-9):
                raise ValueError("preflight intent conflict")
            return
        db.execute("""INSERT INTO autotrader_v3_avoid_loss_preflight_v1
            (request_key,trader_id,account_id,uic,asset_type,
             signed_amount,initial_margin_nok,created_at)
            VALUES(?,?,?,?,?,?,?,?)""",
            (request_key,trader_id,account_id,int(uic),asset_type,
             signed_amount,margin_nok,datetime.now(timezone.utc).isoformat()))


def staged_entry_for_reconciled_order_v1(
    *,trader_id:str,account_id:str,uic:int,asset_type:str,
    db_path="pricegauger.db"):
    """Only a durable RECONCILED OPEN can license a margin anchor.

    This is *necessary* evidence, not proof by itself: caller additionally
    verifies Saxo audit/fill and sole exact individual position.
    """
    ensure_avoid_loss_research_schema_v1(db_path=db_path)
    with connect(db_path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS autotrader_v3_avoid_loss_preflight_v1 (
           request_key TEXT PRIMARY KEY, trader_id TEXT NOT NULL,
           account_id TEXT NOT NULL, uic INTEGER NOT NULL,
           asset_type TEXT NOT NULL, signed_amount DOUBLE PRECISION NOT NULL,
           initial_margin_nok DOUBLE PRECISION NOT NULL,
           created_at TEXT NOT NULL
        )""")
        row=db.execute("""SELECT p.request_key,p.account_id,p.uic,p.asset_type,
               o.state AS guard_state,p.initial_margin_nok,
               p.signed_amount,o.broker_order_id,o.submitted_side,
               o.submitted_amount,o.expected_inventory
            FROM autotrader_v3_avoid_loss_preflight_v1 p
            JOIN autotrader_v3_order_guard o ON o.request_key=p.request_key
            WHERE p.trader_id=? AND p.account_id=? AND p.uic=? AND p.asset_type=?
              AND o.state='RECONCILED' AND o.trader_id=? AND o.account_id=?
              AND o.uic=? AND o.asset_type=? AND o.broker_order_id IS NOT NULL
            ORDER BY p.created_at DESC LIMIT 2""",
            (trader_id,account_id,int(uic),asset_type,
             trader_id,account_id,int(uic),asset_type)).fetchall()
    if len(row)!=1:
        # Multiple candidate entries (past flat + a new open) are ambiguous
        # without an explicit per-lifecycle claim; refuse instead of guessing.
        return None
    return dict(row[0])


def save_avoid_loss_exit_bar_v1(*,trader_id:str,at:datetime,
                                 db_path="pricegauger.db"):
    """Require a fresh *subsequent* completed MACD bar for new exposure."""
    stamp=_utc(at).isoformat()
    ensure_avoid_loss_research_schema_v1(db_path=db_path)
    with connect(db_path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS autotrader_v3_avoid_loss_exit_v1(
          trader_id TEXT PRIMARY KEY, last_exit_signal_at TEXT NOT NULL
        )""")
        db.execute("""INSERT INTO autotrader_v3_avoid_loss_exit_v1(
          trader_id,last_exit_signal_at) VALUES(?,?)
          ON CONFLICT(trader_id) DO UPDATE SET
          last_exit_signal_at=CASE WHEN excluded.last_exit_signal_at>
            autotrader_v3_avoid_loss_exit_v1.last_exit_signal_at
            THEN excluded.last_exit_signal_at
            ELSE autotrader_v3_avoid_loss_exit_v1.last_exit_signal_at END""",
            (trader_id,stamp))


def load_avoid_loss_exit_bar_v1(*,trader_id:str,db_path="pricegauger.db"):
    ensure_avoid_loss_research_schema_v1(db_path=db_path)
    with connect(db_path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS autotrader_v3_avoid_loss_exit_v1(
          trader_id TEXT PRIMARY KEY, last_exit_signal_at TEXT NOT NULL
        )""")
        row=db.execute(
            "SELECT last_exit_signal_at FROM autotrader_v3_avoid_loss_exit_v1 WHERE trader_id=?",
            (trader_id,)).fetchone()
    return datetime.fromisoformat(row["last_exit_signal_at"]) if row else None


__all__=[
    "ensure_avoid_loss_research_schema_v1",
    "register_confirmed_entry_anchor_v1","load_confirmed_entry_anchor_v1",
    "save_risk_state_v1","load_risk_state_v1","retire_confirmed_flat_v1",
    "stage_entry_preflight_v1","staged_entry_for_reconciled_order_v1",
    "save_avoid_loss_exit_bar_v1","load_avoid_loss_exit_bar_v1",
]
