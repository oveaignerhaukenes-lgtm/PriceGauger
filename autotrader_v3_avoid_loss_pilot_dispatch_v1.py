"""Dormant Avoid Loss V1 CLOSE execution adapter (never scheduled or registered).

Designed for a future, separately approved single-account Monday pilot.
OFF by default even if imported. It uses the SAME V3 durable order guard
and Saxo LIVE adapter as all other V3 orders: no independent submitter.
No automatic retry after any unknown broker outcome.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from os import environ
from uuid import NAMESPACE_URL,uuid5

from autotrader_v3_avoid_loss_supervisor_v1 import AvoidLossPilotPlanV1
from autotrader_v3_avoid_loss_state_v1 import (
    load_confirmed_entry_anchor_v1,save_risk_state_v1,
)
from autotrader_v3_live_authority_v1 import live_authority_armed_v3
from autotrader_v3_instance_registry_v1 import load_v3_instances_v1
from autotrader_v3_order_guard_v1 import (
    reserve as reserve_order_v3,
    pending_order as pending_order_v3,
    order_state as order_state_v3,
    claim_reserved_for_submission_v3,
    mark as mark_order_v3,
)
from autotrader_v3_operator_order_recovery_v1 import _assert_no_working_orders_v3
from autotrader_v3_live_saxo_v1 import SaxoLivePilotClientV3
from saxo_provider import SaxoInstrument
from saxo_trading import SaxoOrderRequest

_ALLOWED_MARKET_STATES = frozenset({"open","continuous","continuoustrading","trading"})


@dataclass(frozen=True, slots=True)
class AvoidLossCloseDispatchV1:
    status: str
    reason: str
    # No broker ID in public result; this function never asserts broker FLAT.
    broker_flat: bool = False


class AvoidLossPilotSafetyBlockV1(RuntimeError):
    """An ambiguous/missing LIVE safety contract permanently blocks submit."""


def close_intent_key_v1(*,trader_id:str,position_token:str,signed_amount:float)->str:
    """Stable through restart/retry, unique to a single confirmed lifecycle."""
    if not trader_id or not position_token or not isfinite(float(signed_amount)) or signed_amount==0:
        raise ValueError("complete Saxo position identity is required")
    return str(uuid5(NAMESPACE_URL,
        f"pgv3:avoid-loss-v1:CLOSE:{trader_id}:{position_token}:{signed_amount:.10g}"))


def dispatch_avoid_loss_close_v1(
    *,trader_id:str,plan:AvoidLossPilotPlanV1,broker:SaxoLivePilotClientV3,
    now:datetime,db_path:str="pricegauger.db",
    explicit_pilot_approval:bool=False,
) -> AvoidLossCloseDispatchV1:
    """One-shot exact-account CLOSE through existing durable V3 workflow.

    The function is NOT CALLED from worker, UI, or any live strategy.
    To permit an approved future pilot: caller must explicitly approve,
    three per-pilot server env selectors must match exact identities, the
    isolated V3 instance must be armed and own the account, and broker
    identity/inventory, fresh risk state, working orders and market must
    be checked. NEVER infer live authorization from a strategy selection.
    """
    # Fail before constructing or querying a broker for default-disabled use.
    if not explicit_pilot_approval:
        return AvoidLossCloseDispatchV1("LIVE_DISABLED","EXPLICIT_PILOT_APPROVAL_REQUIRED")
    if environ.get("PG_AVOID_LOSS_V1_LIVE_PILOT_ENABLE")!="enabled":
        return AvoidLossCloseDispatchV1("LIVE_DISABLED","SERVER_FEATURE_FLAG_OFF")
    if not isinstance(plan,AvoidLossPilotPlanV1) or not plan.close_needed or plan.status!="CLOSE_REQUIRED":
        raise AvoidLossPilotSafetyBlockV1("NO_CONFIRMED_CLOSE_INTENT")
    if now.tzinfo is None:
        raise AvoidLossPilotSafetyBlockV1("UTC_CLOCK_REQUIRED")
    if plan.next_state is None or not plan.next_state.exit_pending or plan.next_state.last_sample_at is None:
        raise AvoidLossPilotSafetyBlockV1("DURABLE_STOP_LATCH_REQUIRED")
    delta=(now.astimezone(timezone.utc)-plan.next_state.last_sample_at.astimezone(timezone.utc)).total_seconds()
    if not 0<=delta<=10:
        raise AvoidLossPilotSafetyBlockV1("STALE_CLOSE_SIGNAL")
    instances=tuple(i for i in load_v3_instances_v1(db_path=db_path) if i.instance_id==str(trader_id))
    if len(instances)!=1:
        raise AvoidLossPilotSafetyBlockV1("EXACT_ENABLED_INSTANCE_REQUIRED")
    instance=instances[0]
    if (environ.get("PG_AVOID_LOSS_V1_PILOT_TRADER_ID")!=trader_id
        or environ.get("PG_AVOID_LOSS_V1_PILOT_ACCOUNT_ID")!=instance.account_id):
        raise AvoidLossPilotSafetyBlockV1("EXACT_SERVER_PILOT_SCOPE_REQUIRED")
    from autotrader_engine_account_ownership_v1 import ENGINE_V3,load_account_owner_v1
    owner=load_account_owner_v1(instance.account_id,db_path=db_path)
    if not (live_authority_armed_v3(trader_id,db_path=db_path)
            and owner is not None and owner.engine_id==ENGINE_V3
            and owner.owner_key==trader_id):
        raise AvoidLossPilotSafetyBlockV1("V3_LIVE_AUTHORITY_OR_OWNERSHIP_MISSING")
    position=load_confirmed_entry_anchor_v1(trader_id=trader_id,db_path=db_path)
    if (position is None or position.account_id!=instance.account_id
        or position.uic!=int(instance.uic) or position.asset_type!=instance.asset_type
        or plan.next_state.position_key!=position.key):
        raise AvoidLossPilotSafetyBlockV1("CONFIRMED_ANCHOR_BOUNDARY_MISMATCH")
    if broker is None:
        raise AvoidLossPilotSafetyBlockV1("SAXO_BROKER_UNAVAILABLE")
    key=close_intent_key_v1(trader_id=trader_id,position_token=position.position_token,
                            signed_amount=position.signed_amount)
    existing=order_state_v3(request_key=key,db_path=db_path)
    if existing is not None:
        # Even a REJECTED close MUST NOT be silently replayed under the
        # same request key; operator must first establish broker truth.
        return AvoidLossCloseDispatchV1("WAIT_ORDER","PRIOR_CLOSE_REQUEST_EXISTS")
    if pending_order_v3(account_id=position.account_id,uic=position.uic,
                        asset_type=position.asset_type,db_path=db_path) is not None:
        return AvoidLossCloseDispatchV1("WAIT_ORDER","OTHER_UNRESOLVED_V3_ORDER")
    account_key,_=broker._account_context_exact(position.account_id)
    account_matches=[a for a in broker.accounts()
         if str(a.get("AccountId") or "")==position.account_id and str(a.get("Currency") or "")=="NOK"]
    if len(account_matches)!=1:
        raise AvoidLossPilotSafetyBlockV1("ACCOUNT_CURRENCY_NOT_VERIFIED_NOK")
    market=broker.market_status_exact(account_id=position.account_id,
                    uic=position.uic,asset_type=position.asset_type)
    if (market.is_open is not True or market.quote_error
        or str(market.market_state or "").lower() not in _ALLOWED_MARKET_STATES):
        return AvoidLossCloseDispatchV1("WAIT_MARKET","SAXO_MARKET_NOT_CONFIRMED_OPEN")
    kw={"account_id":position.account_id,"uic":position.uic,"asset_type":position.asset_type}
    _assert_no_working_orders_v3(broker,account_id=position.account_id,
        account_key=account_key,uic=position.uic,asset_type=position.asset_type)
    rows=broker.positions_exact(**kw)
    nets=broker.net_positions_exact(**kw)
    if len(rows)!=1 or len(nets)!=1:
        raise AvoidLossPilotSafetyBlockV1("BROKER_SINGLE_POSITION_NOT_PROVEN")
    row=rows[0]
    base=row.get("PositionBase") or {}
    signed=broker.signed_inventory_exact(**kw)
    if (str(row.get("PositionId") or "")!=position.position_token
        or str(base.get("AccountId") or base.get("PositionsAccount") or "")!=position.account_id
        or int(base.get("Uic") or -1)!=position.uic
        or str(base.get("AssetType") or "")!=position.asset_type
        or str(base.get("Status") or "").lower() not in {"open","partiallyclosed"}
        or not isfinite(float(signed)) or abs(signed-position.signed_amount)>1e-9
        or abs(abs(float(base.get("Amount")))-abs(signed))>1e-9):
        raise AvoidLossPilotSafetyBlockV1("EXACT_POSITION_OR_SIZE_CHANGED")
    # CLOSE of EXACT existing position only, no speculative reversal/ADD.
    side="Sell" if signed>0 else "Buy"
    order=SaxoOrderRequest(account_key=account_key,
        instrument=SaxoInstrument(asset=instance.market_name,uic=position.uic,
             asset_type=position.asset_type),
        amount=abs(signed),buy_sell=side,external_reference=("pgv3-"+key)[-50:])
    # Guard existence is checked again around precheck; a precheck alone is
    # not an order. It may still fail if the exchange has just closed.
    checked=broker.precheck(order)
    if str(checked.get("PreCheckResult") or checked.get("Result") or "").lower() not in {"ok","passed","success"}:
        raise AvoidLossPilotSafetyBlockV1("SAXO_CLOSE_PRECHECK_NOT_APPROVED")
    _assert_no_working_orders_v3(broker,account_id=position.account_id,
        account_key=account_key,uic=position.uic,asset_type=position.asset_type)
    if abs(broker.signed_inventory_exact(**kw)-signed)>1e-9:
        raise AvoidLossPilotSafetyBlockV1("INVENTORY_CHANGED_DURING_PRECLOSE")
    # Persist a STOP LATCH BEFORE acquiring the durable mutation key.
    # If this fails, nothing can go to Saxo.
    save_risk_state_v1(trader_id=trader_id,state=plan.next_state,db_path=db_path)
    inserted=reserve_order_v3(request_key=key,trader_id=trader_id,
        account_id=position.account_id,uic=position.uic,asset_type=position.asset_type,
        expected_inventory=0.,submitted_amount=abs(signed),submitted_side=side,
        db_path=db_path,idempotent=True)
    if not inserted:
        return AvoidLossCloseDispatchV1("WAIT_ORDER","DURABLE_RESERVATION_CONFLICT")
    if not claim_reserved_for_submission_v3(request_key=key,db_path=db_path):
        return AvoidLossCloseDispatchV1("WAIT_ORDER","CAS_SUBMISSION_AUTHORITY_LOST")
    try:
        result=broker.place_order(order,confirm_live=True)
    except Exception:
        # Even on an apparent HTTP 4xx, conservative UNKNOWN. A timeout,
        # dropped connection or delayed final fill must never lead to a retry.
        mark_order_v3(request_key=key,state="UNKNOWN",
                      detail="Avoid Loss CLOSE result not broker-confirmed; no retry",
                      db_path=db_path)
        return AvoidLossCloseDispatchV1("UNKNOWN","BROKER_CLOSE_RESULT_UNKNOWN")
    broker_id=str(result.get("OrderId") or "").strip() if isinstance(result,dict) else ""
    if not broker_id:
        mark_order_v3(request_key=key,state="UNKNOWN",
                      detail="Avoid Loss CLOSE missing Saxo OrderId; no retry",db_path=db_path)
        return AvoidLossCloseDispatchV1("UNKNOWN","BROKER_CLOSE_ORDER_ID_MISSING")
    mark_order_v3(request_key=key,state="SUBMITTED",broker_order_id=broker_id,
                  detail="Avoid Loss CLOSE submitted; exact Saxo fill/FLAT pending",
                  db_path=db_path)
    return AvoidLossCloseDispatchV1("SUBMITTED","WAIT_BROKER_FINAL_FILL_AND_FLAT")


__all__=["AvoidLossPilotSafetyBlockV1","AvoidLossCloseDispatchV1",
         "close_intent_key_v1","dispatch_avoid_loss_close_v1"]
