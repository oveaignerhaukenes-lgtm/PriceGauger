"""Durable Avoid Loss V1 pilot lifecycle coordinator (never auto-scheduled).

Uses existing research tables and durable V3 order guard, but cannot place
Saxo orders. A successful CLOSE POST never retires the margin anchor:
independent account-scoped Saxo FinalFill + two fresh FLAT reads are required.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from autotrader_v3_avoid_loss_broker_lifecycle_v1 import (
    require_confirmed_final_fill_v1,require_broker_confirmed_flat_v1,
)
from autotrader_v3_avoid_loss_state_v1 import (
    load_confirmed_entry_anchor_v1, load_risk_state_v1,
    save_risk_state_v1, save_avoid_loss_exit_bar_v1,
    retire_confirmed_flat_v1,
)
from autotrader_v3_avoid_loss_supervisor_v1 import AvoidLossPilotPlanV1
from autotrader_v3_order_guard_v1 import (
    order_state as order_state_v3,
    pending_order as pending_order_v3,
)
from autotrader_v3_operator_order_recovery_v1 import _assert_no_working_orders_v3
from autotrader_v3_avoid_loss_pilot_dispatch_v1 import close_intent_key_v1


@dataclass(frozen=True, slots=True)
class CloseReconciliationV1:
    status: str
    code: str
    position_retired: bool = False


def persist_avoid_loss_plan_v1(
    *, trader_id: str, plan: AvoidLossPilotPlanV1,
    db_path: str = "pricegauger.db",
) -> None:
    """Persist HWM/stop BEFORE any CLOSE attempt, refuse invalid states."""
    if not isinstance(plan,AvoidLossPilotPlanV1):
        raise ValueError("invalid Avoid Loss plan")
    if plan.status not in {"MONITORING","CLOSE_REQUIRED"} or plan.next_state is None:
        raise ValueError("only fresh verified LIVE P/L plans can update stop memory")
    if plan.status=="CLOSE_REQUIRED" and (not plan.close_needed
                                           or not plan.next_state.exit_pending):
        raise ValueError("sticky CLOSE latch is required")
    save_risk_state_v1(trader_id=trader_id,state=plan.next_state,db_path=db_path)


def reconcile_avoid_loss_close_v1(
    *, trader_id: str, broker,
    now: datetime, db_path: str = "pricegauger.db",
) -> CloseReconciliationV1:
    """Broker-readonly verification then retire exact anchor after final fill.

    This is an operator-invoked, single-account verified lifecycle step;
    not a worker action. On ANY exception, no anchor is retired.
    """
    if not isinstance(now,datetime) or now.tzinfo is None:
        return CloseReconciliationV1("BLOCKED","UTC_CLOCK_REQUIRED")
    position=load_confirmed_entry_anchor_v1(trader_id=trader_id,db_path=db_path)
    if position is None:
        return CloseReconciliationV1("BLOCKED","CONFIRMED_ANCHOR_MISSING")
    state=load_risk_state_v1(trader_id=trader_id,db_path=db_path)
    if state is None or not state.exit_pending or state.position_key!=position.key:
        return CloseReconciliationV1("BLOCKED","STOP_LATCH_MISSING")
    key=close_intent_key_v1(
        trader_id=trader_id,position_token=position.position_token,
        signed_amount=position.signed_amount)
    if order_state_v3(request_key=key,db_path=db_path)!="RECONCILED":
        return CloseReconciliationV1("WAIT_ORDER","V3_CLOSE_NOT_RECONCILED")
    if pending_order_v3(account_id=position.account_id,uic=position.uic,
                         asset_type=position.asset_type,db_path=db_path) is not None:
        return CloseReconciliationV1("WAIT_ORDER","V3_BOUNDARY_STILL_LOCKED")
    if broker is None:
        return CloseReconciliationV1("BLOCKED","SAXO_READ_UNAVAILABLE")
    try:
        from autotrader_v3_instance_registry_v1 import load_v3_instances_v1
        matches=[i for i in load_v3_instances_v1(db_path=db_path)
            if i.instance_id==trader_id and i.account_id==position.account_id
            and i.uic==position.uic and i.asset_type==position.asset_type]
        if len(matches)!=1:
            return CloseReconciliationV1("BLOCKED","INSTANCE_BOUNDARY_NOT_PROVEN")
        account_key,_=broker._account_context_exact(position.account_id)
        kw={"account_id":position.account_id,"uic":position.uic,"asset_type":position.asset_type}
        accounts=[a for a in broker.accounts()
             if str(a.get("AccountId") or "")==position.account_id
                and str(a.get("Currency") or "")=="NOK"]
        if len(accounts)!=1:
            return CloseReconciliationV1("BLOCKED","EXACT_NOK_ACCOUNT_UNVERIFIED")
        _assert_no_working_orders_v3(
            broker,account_id=position.account_id,account_key=account_key,
            uic=position.uic,asset_type=position.asset_type)
        for _ in range(2):
            net=broker.net_positions_exact(**kw)
            individuals=broker.positions_exact(**kw)
            require_broker_confirmed_flat_v1(
                account_scoped_net_rows=net,
                account_scoped_individual_rows=individuals,
                unresolved_order=False,
            )
        # Broker activity must be independently matched to exact OrderId.
        from database import connect
        with connect(db_path) as db:
            row=db.execute("""SELECT broker_order_id FROM autotrader_v3_order_guard
                 WHERE request_key=? AND trader_id=? AND account_id=? AND uic=?
                    AND asset_type=? AND state='RECONCILED'""",
                    (key,trader_id,position.account_id,position.uic,
                     position.asset_type)).fetchone()
        if row is None or not row["broker_order_id"]:
            return CloseReconciliationV1("BLOCKED","CLOSE_ORDER_ID_NOT_DURABLE")
        activity=broker.order_activity_exact(
            account_id=position.account_id,
            order_id=str(row["broker_order_id"]),
            uic=position.uic,asset_type=position.asset_type)
        require_confirmed_final_fill_v1(
            activity=activity,
            expected_side="Sell" if position.signed_amount>0 else "Buy",
            expected_amount=abs(position.signed_amount),
            expected_position_id=position.position_token,
        )
        # Repeat checks before durable retirement; no working Saxo orders.
        _assert_no_working_orders_v3(
            broker,account_id=position.account_id,account_key=account_key,
            uic=position.uic,asset_type=position.asset_type)
        require_broker_confirmed_flat_v1(
            account_scoped_net_rows=broker.net_positions_exact(**kw),
            account_scoped_individual_rows=broker.positions_exact(**kw),
            unresolved_order=pending_order_v3(
                account_id=position.account_id,uic=position.uic,
                asset_type=position.asset_type,db_path=db_path) is not None,
        )
    except Exception:
        # Never publish broker raw errors or leak ids.
        return CloseReconciliationV1("UNPROTECTED","BROKER_CLOSE_EVIDENCE_UNVERIFIED")
    # Persist the re-entry barrier before clearing an immutable anchor.
    save_avoid_loss_exit_bar_v1(
        trader_id=trader_id,at=now.astimezone(timezone.utc),db_path=db_path)
    retired=retire_confirmed_flat_v1(
        trader_id=trader_id,broker_exact_flat=True,db_path=db_path)
    if not retired:
        return CloseReconciliationV1("BLOCKED","ANCHOR_RETIRED_CONCURRENTLY")
    return CloseReconciliationV1("BROKER_FLAT_VERIFIED","FINAL_FILL_AND_ZERO_INVENTORY",True)


__all__=["CloseReconciliationV1","persist_avoid_loss_plan_v1",
         "reconcile_avoid_loss_close_v1"]
