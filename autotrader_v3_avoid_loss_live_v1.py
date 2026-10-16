"""Exact-account Saxo P/L observer for Unngå tap V1 (read-only broker adapter).

It never POSTs Saxo orders. On confirmed threshold breaches it persists a
sticky EXIT_PENDING latch and aligns V3's closed-bar target to FLAT. The EXISTING
single-threaded V3 LIVE durable order pipeline alone submits/reconciles CLOSE.

The caller must invoke the V3 LIVE cycle immediately after a close request;
a stopped app or nontrading exchange cannot guarantee the 1% limit.
"""
from __future__ import annotations

import logging
from datetime import datetime,timezone
from math import isfinite

from autotrader_v3_avoid_loss_v1 import (
    ConfirmedPositionV1,inspect_open_position_v1,STRATEGY_KEY_V1,
)
from autotrader_v3_avoid_loss_saxo_evidence_v1 import validated_saxo_position_pnl_v1
from autotrader_v3_avoid_loss_state_v1 import (
    ensure_avoid_loss_research_schema_v1,load_confirmed_entry_anchor_v1,
    load_risk_state_v1,save_risk_state_v1,
    staged_entry_for_reconciled_order_v1,register_confirmed_entry_anchor_v1,
    retire_confirmed_flat_v1,save_avoid_loss_exit_bar_v1,
)
from autotrader_v3_closed_bar_driver_v1 import align_closed_bar_target_v3
from autotrader_v3_live_saxo_v1 import configured_live_pilot_client_v3
from autotrader_v3_order_guard_v1 import pending_order as pending_order_v3
from autotrader_v3_runtime_instances_v1 import load_v3_runtime_instances_v1
from autotrader_v3_live_authority_v1 import live_authority_armed_v3
from autotrader_engine_account_ownership_v1 import ENGINE_V3,load_account_owner_v1
from autotrader_v3_config_v1 import load_autotrader_config_v3
from database import connect

LOGGER=logging.getLogger("pricegauger.autotrader.v3.avoid_loss")
RISK_CHECK_SECONDS=5.0


def _status(trader_id,status,detail,*,db_path):
    """Status log is explicit: an unavailable stop is NOT reported as protected."""
    LOGGER.warning("avoid-loss risk trader=%s status=%s detail=%s",trader_id,status,detail)
    with connect(db_path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS autotrader_v3_avoid_loss_monitor_v1(
            trader_id TEXT PRIMARY KEY,status TEXT NOT NULL,
            detail TEXT NOT NULL,updated_at TEXT NOT NULL
        )""")
        db.execute("""INSERT INTO autotrader_v3_avoid_loss_monitor_v1(
          trader_id,status,detail,updated_at) VALUES(?,?,?,?)
          ON CONFLICT(trader_id) DO UPDATE SET
          status=excluded.status,detail=excluded.detail,
          updated_at=excluded.updated_at""",
          (trader_id,status,detail,datetime.now(timezone.utc).isoformat()))


def active_avoid_loss_traders_v1(*,db_path="pricegauger.db"):
    """Respect exact account owner and explicit LIVE authority before ANY read."""
    result=[]
    for instance in load_v3_runtime_instances_v1(db_path=db_path):
        if instance.strategy_key!=STRATEGY_KEY_V1:
            continue
        if not live_authority_armed_v3(instance.pilot_key,db_path=db_path):
            continue
        if load_autotrader_config_v3(instance.pilot_key,db_path=db_path).timeframe!="2m":
            continue
        owner=load_account_owner_v1(instance.account_id,db_path=db_path)
        if owner is None or owner.engine_id!=ENGINE_V3 or owner.owner_key!=instance.pilot_key:
            continue
        result.append(instance)
    return tuple(result)


def _single_exact_position(broker,e,amount):
    rows=broker.positions_exact(account_id=e.account_id,uic=e.uic,
                                asset_type=e.asset_type)
    if len(rows)!=1:
        raise ValueError("expected exactly one Saxo PositionId for the position")
    row=rows[0]
    base=row.get("PositionBase") or {}
    direction=str(base.get("OpeningDirection") or "").lower()
    signed=float(base.get("Amount") or 0)*(1 if direction=="buy" else
         -1 if direction=="sell" else 0)
    if abs(signed-float(amount))>1e-9:
        raise ValueError("Saxo individual position amount differs from net inventory")
    return row


def _check_confirmed_open(broker,e,position,*,db_path):
    stage=staged_entry_for_reconciled_order_v1(
        trader_id=e.pilot_key,account_id=e.account_id,uic=int(e.uic),
        asset_type=e.asset_type,db_path=db_path)
    if not stage:
        raise ValueError("no unique matched RECONCILED OPEN margin stage")
    side="Buy" if position>0 else "Sell"
    if str(stage["submitted_side"])!=side:
        raise ValueError("RECONCILED Saxo opening direction mismatch")
    if abs(float(stage["signed_amount"])-position)>1e-9:
        raise ValueError("Saxo net/confirmed opening size mismatch")
    if abs(float(stage["submitted_amount"])-abs(position))>1e-9:
        raise ValueError("Saxo submitted amount different from actual size")
    if abs(float(stage["expected_inventory"])-position)>1e-9:
        raise ValueError("Saxo expected inventory mismatch")
    audit=broker.order_activity_exact(
        account_id=e.account_id,order_id=str(stage["broker_order_id"]),
        uic=int(e.uic),asset_type=e.asset_type)
    if not audit.get("available"):
        raise ValueError("Saxo ORDER_HISTORY unavailable: do not anchor")
    status=str(audit.get("status") or "").lower()
    if status not in {"filled","executed","done","fullyfilled","completed"}:
        raise ValueError("Saxo ORDER_HISTORY does not prove executed full fill")
    if str(audit.get("side") or "").title()!=side:
        raise ValueError("Saxo ORDER_HISTORY opposite side")
    filled=float(audit.get("filled_amount") or 0)
    if not isfinite(filled) or abs(filled-abs(position))>1e-9:
        raise ValueError("Saxo full fill amount not verified")
    return stage


def run_avoid_loss_live_risk_once(*,db_path="pricegauger.db",now=None):
    """Return trader IDs requiring the existing V3 guarded CLOSE cycle.

    Each invocation is read-only against Saxo, and cannot alter any trade
    account. No user config or arming changes. A watchdog failure MUST be
    surfaced as UNPROTECTED, not silent 'HOLD'.
    """
    enrolled=active_avoid_loss_traders_v1(db_path=db_path)
    if not enrolled:return ()
    clock=now or datetime.now(timezone.utc)
    broker=configured_live_pilot_client_v3()
    if broker is None:
        for e in enrolled:
            _status(e.pilot_key,"UNPROTECTED","Saxo LIVE client unavailable",db_path=db_path)
        return ()
    accounts={str(a.get("AccountId")):a for a in broker.accounts()
              if isinstance(a,dict)}
    requested=[]
    for e in enrolled:
        try:
            acc=accounts.get(e.account_id)
            if not acc or str(acc.get("Currency") or "").upper()!="NOK":
                raise ValueError("Saxo exact account NOK currency unverified")
            pending=pending_order_v3(account_id=e.account_id,uic=int(e.uic),
                    asset_type=e.asset_type,db_path=db_path)
            # No stop request while the broker's previous mutation is unresolved.
            if pending:
                _status(e.pilot_key,"PENDING",
                        "Saxo mutation unresolved; cannot claim protected exit",
                        db_path=db_path)
                continue
            amount=broker.signed_inventory_exact(account_id=e.account_id,
                       uic=int(e.uic),asset_type=e.asset_type)
            anchor=load_confirmed_entry_anchor_v1(trader_id=e.pilot_key,
                                                       db_path=db_path)
            if abs(amount)<=1e-12:
                if anchor:
                    actual=broker.positions_exact(account_id=e.account_id,
                        uic=int(e.uic),asset_type=e.asset_type)
                    if actual:
                        raise ValueError("net FLAT but individual Saxo position still open")
                    # This lifecycle is complete, now require a new 2m bar
                    # BEFORE the normal MACD entry engine may open again.
                    save_avoid_loss_exit_bar_v1(
                        trader_id=e.pilot_key,at=clock,db_path=db_path)
                    retire_confirmed_flat_v1(
                        trader_id=e.pilot_key,broker_exact_flat=True,db_path=db_path)
                _status(e.pilot_key,"FLAT","No broker exposure; awaiting new 2m signal",
                        db_path=db_path)
                continue
            pos_row=_single_exact_position(broker,e,amount)
            if anchor is None:
                stage=_check_confirmed_open(broker,e,amount,db_path=db_path)
                anchor=ConfirmedPositionV1(
                    account_id=e.account_id,uic=int(e.uic),
                    asset_type=e.asset_type,position_token=str(pos_row["PositionId"]),
                    signed_amount=amount,entry_margin_nok=float(stage["initial_margin_nok"]))
                register_confirmed_entry_anchor_v1(
                    trader_id=e.pilot_key,position=anchor,
                    reconciled_open_request_key=str(stage["request_key"]),
                    confirmed_order_id=str(stage["broker_order_id"]),
                    confirmed_at=clock,db_path=db_path)
            if abs(anchor.signed_amount-amount)>1e-9:
                raise ValueError("position changed; frozen Saxo margin is no longer valid")
            sample=validated_saxo_position_pnl_v1(
                row=pos_row,position=anchor,account_currency="NOK",
                estimated_exit_cost_nok=0.0,received_at=clock)
            previous=load_risk_state_v1(trader_id=e.pilot_key,db_path=db_path)
            decision=inspect_open_position_v1(
                position=anchor,sample=sample,state=previous,now=clock)
            if decision.action=="BLOCKED":
                raise ValueError(decision.reason)
            if decision.state:
                save_risk_state_v1(trader_id=e.pilot_key,
                                    state=decision.state,db_path=db_path)
            if decision.action in {"REQUEST_CLOSE","WAIT_RECONCILE"}:
                # Never replay last LONG/SHORT desired inventory while STOP is latched.
                align_closed_bar_target_v3(
                    trader_id=e.pilot_key,target_amount=0.0,db_path=db_path)
                _status(e.pilot_key,"STOP_PENDING",
                        f"{decision.reason}; P/L={decision.pnl_pct:+.3f}% "
                        f"peak={decision.peak_pct:+.3f}% "
                        "Saxo FLAT not yet confirmed",db_path=db_path)
                requested.append(e.pilot_key)
            else:
                _status(e.pilot_key,"PROTECTED",
                        f"exact PositionId verified; P/L={decision.pnl_pct:+.3f}% "
                        f"peak={decision.peak_pct:+.3f}% "
                        f"trail_floor={decision.floor_pct}",db_path=db_path)
        except Exception as exc:
            _status(e.pilot_key,"UNPROTECTED",
                    f"{type(exc).__name__}: {str(exc)[:190]}",db_path=db_path)
    return tuple(requested)


__all__=["RISK_CHECK_SECONDS","active_avoid_loss_traders_v1",
         "run_avoid_loss_live_risk_once"]
