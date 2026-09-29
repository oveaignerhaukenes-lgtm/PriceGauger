from __future__ import annotations
import logging
from uuid import uuid5, NAMESPACE_URL
from datetime import datetime,timedelta,timezone
from autotrader_mtf_entry_shadow_v2 import closed_bars_v2,macd_observations_v2
from autotrader_risk_control_v2 import _position_observations_v2
from autotrader_strategy_enrollment_v2 import load_active_strategy_enrollments_v2,EXECUTION_MODE_LIVE
from autotrader_v3_strategy_registry_v1 import STRATEGIES_V3, evaluate_strategy_bar_v3
from autotrader_v3_domain import AccountBoundaryV3,TargetInventoryV3,signed_inventory_v3
from autotrader_v3_execution_plan_v1 import plan_execution_v3
from autotrader_v3_live_authority_v1 import live_authority_armed_v3
from autotrader_v3_order_guard_v1 import reserve as reserve_order_v3, mark as mark_order_v3, unresolved as unresolved_order_v3, pending_order as pending_order_v3
from autotrader_v3_order_reconciliation_v1 import reconcile_pending_v3
from database import connect
from autotrader_v3_live_saxo_v1 import configured_live_pilot_client_v3
from autotrader_v3_macd_histogram_v1 import STRATEGY_KEY_V3
from autotrader_v3_macd_trailing_v1 import STRATEGY_KEY_V3 as TRAILING_KEY
from autotrader_v3_pipeline_v1 import TraderV3,evaluate_trader_v3
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from saxo_provider import SaxoInstrument
from saxo_trading import SaxoOrderRequest

LOGGER=logging.getLogger("pricegauger.autotrader.v3.live")

def _record_runtime(trader_id, status, detail="", *, db_path="pricegauger.db"):
    with connect(db_path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS autotrader_v3_live_runtime_state(
          trader_id TEXT PRIMARY KEY,status TEXT NOT NULL,detail TEXT,updated_at TEXT NOT NULL)""")
        db.execute("""INSERT INTO autotrader_v3_live_runtime_state(trader_id,status,detail,updated_at)
          VALUES(?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(trader_id) DO UPDATE SET
          status=excluded.status,detail=excluded.detail,updated_at=excluded.updated_at""",(trader_id,status,detail))

def _actual(e,observations):
    matches=[o for o in observations if o.account_id==e.account_id and int(o.uic)==int(e.uic) and o.asset_type==e.asset_type]
    if len(matches)>1: raise RuntimeError("ambiguous exact v3 Saxo boundary")
    return TargetInventoryV3(0) if not matches else signed_inventory_v3(direction=matches[0].direction,amount=matches[0].amount)

def run_v3_live_cycle_v1(*,db_path="pricegauger.db",now=None)->int:
    """Normal v3 LIVE runtime. The LIVE toggle is the user authority boundary."""
    active=tuple(e for e in load_active_strategy_enrollments_v2()
        if e.execution_mode==EXECUTION_MODE_LIVE
        and live_authority_armed_v3(e.pilot_key,db_path=db_path))
    # Strategy selection is registry-driven. LIVE route availability is intentionally
    # separate: trailing has a planner but lacks durable Saxo reconciliation.
    # Do not substitute another strategy when the selected one is blocked.
    for e in active:
        adapter = STRATEGIES_V3.get(e.strategy_key)
        if adapter is None:
            _record_runtime(e.pilot_key, "BLOCKED",
                f"Unregistered V3 strategy {e.strategy_key}; no orders sent.", db_path=db_path)
        elif not adapter.live_route_enabled:
            _record_runtime(e.pilot_key, "BLOCKED",
                f"{e.strategy_key}: LIVE execution/reconciliation not validated. No orders sent.",
                db_path=db_path)
    enrollments=tuple(e for e in active if
        (adapter := STRATEGIES_V3.get(e.strategy_key)) is not None
        and adapter.live_route_enabled)
    if not enrollments: return 0
    # Record the heartbeat before any external dependency. If setup fails after
    # authority is armed, the UI must show the failure instead of "no heartbeat".
    for e in enrollments:
        _record_runtime(e.pilot_key,"RUNNING","worker cycle entered",db_path=db_path)
    try:
        broker=configured_live_pilot_client_v3()
        if broker is None:
            raise RuntimeError("Saxo LIVE client unavailable")
        observations=_position_observations_v2(broker.client)
    except Exception as exc:
        for e in enrollments:
            _record_runtime(e.pilot_key,"FAILED",f"{type(exc).__name__}: {exc}",db_path=db_path)
        raise
    # Saxo account endpoint returns JSON dictionaries, not account objects.
    # Treating them as attributes made every armed v3 cycle fail before execution.
    accounts={}
    account_contexts={}
    for row in broker.accounts():
        if not isinstance(row,dict):
            continue
        account_id=str(row.get("AccountId") or "").strip()
        account_key=str(row.get("AccountKey") or "").strip()
        if account_id and account_key:
            accounts[account_id]=account_key
            account_contexts[account_id]=(account_key,str(row.get('ClientKey') or ''))
    executed=0; end=now or datetime.now(timezone.utc)
    for e in enrollments:
        # Reconcile before computing a new signal: locks must be handled even
        # when market data is missing or the latest strategy target is HOLD.
        pending=pending_order_v3(account_id=e.account_id,uic=e.uic,
                                 asset_type=e.asset_type,db_path=db_path)
        if pending:
            context=account_contexts.get(e.account_id)
            reconciled=False
            if context:
                try:
                    reconciled=reconcile_pending_v3(
                        broker=broker,pending=pending,account_id=e.account_id,
                        uic=e.uic,asset_type=e.asset_type,
                        account_key=context[0],client_key=context[1],
                        read_positions=_position_observations_v2,
                        mark_reconciled=mark_order_v3,db_path=db_path)
                except Exception as exc:
                    # Persist only a bounded phase/type. The chained exception is
                    # available to server logs without exposing broker payloads in UI.
                    from autotrader_v3_order_reconciliation_v1 import V3ReconciliationPhaseError
                    if isinstance(exc, V3ReconciliationPhaseError):
                        safe_detail = str(exc)
                    else:
                        safe_detail = f'unknown_phase: {type(exc).__name__}'
                    LOGGER.error('v3 reconciliation blocked pilot=%s phase_error=%s',
                        e.pilot_key, safe_detail)
                    _record_runtime(e.pilot_key,'BLOCKED',
                        f'Order reconciliation unavailable: {safe_detail}',db_path=db_path)
                    continue
            _record_runtime(e.pilot_key,'RECONCILED' if reconciled else 'BLOCKED',
                'Saxo FinalFill and exact inventory confirmed; next cycle may trade'
                if reconciled else 'Unresolved Saxo order: awaiting exact fill and inventory',
                db_path=db_path)
            continue
        actual=_actual(e,observations)
        bars=CanonicalMarketBarStoreV2(db_path).load_instrument_range(instrument_id=e.instrument_id,start=end-timedelta(days=14),end=end,limit=20000)
        closed=closed_bars_v2(tuple(b.point for b in bars),market=e.market_name,timeframe_minutes=5) if bars else ()
        obs=macd_observations_v2(closed,timeframe_minutes=5) if closed else ()
        if not obs:
            _record_runtime(e.pilot_key,"DEGRADED","no closed 5m MACD observation",db_path=db_path)
            continue
        decision=evaluate_strategy_bar_v3(trader_id=e.pilot_key,observation=obs[-1],strategy_key=e.strategy_key,db_path=db_path)
        trader=TraderV3(e.pilot_key,AccountBoundaryV3(e.account_id,int(e.uic),e.asset_type),e.strategy_key)
        snapshot=evaluate_trader_v3(trader=trader,base_target=decision.decision.target,actual_inventory=actual).snapshot
        plan=plan_execution_v3(snapshot)
        mutation=next((s for s in plan.steps if s.action in {"OPEN","ADD","REDUCE","CLOSE"}),None)
        if mutation is None:
            _record_runtime(e.pilot_key,"MANAGING",f"target={snapshot.risk_approved_target.amount:g} actual={actual.amount:g}",db_path=db_path)
            continue
        # Manual-seeded trailing pilot: only reduce an existing position.
        # Keep the durable guard and Saxo precheck for any reduction.
        if e.strategy_key == TRAILING_KEY:
            if mutation.action not in {"REDUCE", "CLOSE"}:
                _record_runtime(e.pilot_key, "MANAGING",
                    "Trailing manual pilot: waiting for manual position or reduction signal",
                    db_path=db_path)
                continue
            if actual.amount == 0 or mutation.amount > abs(actual.amount) + 1e-9:
                _record_runtime(e.pilot_key, "BLOCKED",
                    "Trailing manual pilot: reduction exceeds exact current position",
                    db_path=db_path)
                continue
        # Saxo fractional CFD quantities are accepted at two decimal places for this
        # small Tech100 pilot. Never round up a reduce-only order, and never send
        # a zero/sub-minimum order to precheck in a retry loop.
        if e.strategy_key == TRAILING_KEY:
            from decimal import Decimal, ROUND_DOWN
            requested = Decimal(str(mutation.amount))
            permitted = requested.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
            if permitted < Decimal("0.01"):
                _record_runtime(e.pilot_key, "BLOCKED",
                    "Trailing manual pilot: reduction below 0.01 Saxo order step",
                    db_path=db_path)
                continue
            if permitted != requested:
                from autotrader_v3_execution_plan_v1 import ExecutionStepV3
                mutation = ExecutionStepV3(mutation.action, float(permitted),
                    mutation.direction, mutation.requires_flat_confirmation,
                    mutation.reason + "; floored to 0.01 Saxo order step")
        account=accounts.get(e.account_id)
        if account is None: raise RuntimeError(f"v3 LIVE account unavailable: {e.account_id}")
        side=("Buy" if mutation.direction=="LONG" else "Sell")
        if mutation.action in {"REDUCE","CLOSE"}: side=("Sell" if mutation.direction=="LONG" else "Buy")
        instrument=SaxoInstrument(asset=e.market_name,uic=int(e.uic),asset_type=e.asset_type)
        # CLOSE and OPEN of one reversal must have distinct durable identities.
        # A retry of the same mutation retains its original identity.
        signed_delta=mutation.amount if side=='Buy' else -mutation.amount
        request_key=str(uuid5(NAMESPACE_URL,
            f'{e.pilot_key}:{decision.decision_key}:{mutation.action}:{side}:'
            f'{actual.amount:.10g}:{mutation.amount:.10g}'))
        order=SaxoOrderRequest(account_key=account,instrument=instrument,amount=mutation.amount,buy_sell=side,
            external_reference=('pgv3-'+request_key)[-50:])
        pre=broker.precheck(order)
        if str(pre.get("PreCheckResult") or pre.get("Result") or "").lower() not in {"ok","passed","success"}:
            raise RuntimeError(f"v3 LIVE precheck rejected: {pre}")
        # Persist before the external POST; a timeout is UNKNOWN, never a retry.
        reserve_order_v3(request_key=request_key,trader_id=e.pilot_key,
            account_id=e.account_id,uic=e.uic,asset_type=e.asset_type,
            expected_inventory=actual.amount+signed_delta,
            submitted_amount=mutation.amount,submitted_side=side,db_path=db_path)
        mark_order_v3(request_key=request_key,state='SUBMITTING',db_path=db_path)
        try:
            result=broker.place_order(order,confirm_live=True)
        except Exception as exc:
            mark_order_v3(request_key=request_key,state='UNKNOWN',
                detail=f'{type(exc).__name__}: {exc}',db_path=db_path)
            _record_runtime(e.pilot_key,'BLOCKED','Saxo order result unknown; reconcile before retry',db_path=db_path)
            raise
        broker_order_id=str(result.get('OrderId') or '').strip() if isinstance(result,dict) else ''
        if not broker_order_id:
            mark_order_v3(request_key=request_key,state='UNKNOWN',
                detail='Saxo accepted request but response lacks a verifiable OrderId',db_path=db_path)
            _record_runtime(e.pilot_key,'BLOCKED','Saxo response lacks OrderId; manual reconciliation required',db_path=db_path)
            continue
        mark_order_v3(request_key=request_key,state='SUBMITTED',
            broker_order_id=broker_order_id,db_path=db_path)
        executed+=1
        _record_runtime(e.pilot_key,"MANAGING",f"executed {mutation.action} {side} {mutation.amount:g}",db_path=db_path)
        LOGGER.warning("v3 LIVE executed trader=%s step=%s side=%s amount=%s",e.pilot_key,mutation.action,side,mutation.amount)
    return executed
