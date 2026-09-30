from __future__ import annotations
import logging
from uuid import uuid5, NAMESPACE_URL
from datetime import datetime,timedelta,timezone
from autotrader_mtf_entry_shadow_v2 import closed_bars_v2,macd_observations_v2
from autotrader_strategy_enrollment_v2 import load_active_strategy_enrollments_v2,EXECUTION_MODE_LIVE
from autotrader_v3_strategy_registry_v1 import STRATEGIES_V3, evaluate_strategy_bar_v3
from autotrader_v3_domain import AccountBoundaryV3,TargetInventoryV3,signed_inventory_v3
from autotrader_v3_execution_plan_v1 import plan_execution_v3
from autotrader_v3_live_authority_v1 import live_authority_armed_v3
from autotrader_v3_order_guard_v1 import reserve as reserve_order_v3, mark as mark_order_v3, unresolved as unresolved_order_v3, pending_order as pending_order_v3
from database import connect
from autotrader_v3_live_saxo_v1 import configured_live_pilot_client_v3
from autotrader_v3_macd_histogram_v1 import STRATEGY_KEY_V3
from autotrader_v3_macd_trailing_v1 import STRATEGY_KEY_V3 as TRAILING_KEY
from autotrader_v3_pipeline_v1 import TraderV3,evaluate_trader_v3
from autotrader_v3_position_reconcile_v1 import reconcile_position_v3
from autotrader_v3_execution_policy_v1 import load_execution_policy_v3
from autotrader_v3_live_sizing_v1 import cap_open_add_amount_v3
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from saxo_provider import SaxoInstrument
from saxo_trading import SaxoOrderRequest

LOGGER=logging.getLogger("pricegauger.autotrader.v3.live")

def _record_runtime(trader_id, status, detail="", *, db_path="pricegauger.db"):
    LOGGER.info("v3 runtime trader=%s status=%s detail=%s",trader_id,status,detail)
    with connect(db_path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS autotrader_v3_live_runtime_state(
          trader_id TEXT PRIMARY KEY,status TEXT NOT NULL,detail TEXT,updated_at TEXT NOT NULL)""")
        db.execute("""INSERT INTO autotrader_v3_live_runtime_state(trader_id,status,detail,updated_at)
          VALUES(?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(trader_id) DO UPDATE SET
          status=excluded.status,detail=excluded.detail,updated_at=excluded.updated_at""",(trader_id,status,detail))

def _actual(e,broker):
    return TargetInventoryV3(broker.signed_inventory_exact(
        account_id=e.account_id,uic=int(e.uic),asset_type=e.asset_type))

def run_v3_live_cycle_v1(*,db_path="pricegauger.db",now=None)->int:
    """Normal v3 LIVE runtime. The LIVE toggle is the user authority boundary."""
    loaded=load_active_strategy_enrollments_v2()
    live=tuple(e for e in loaded if e.execution_mode==EXECUTION_MODE_LIVE)
    armed=tuple(e for e in live if live_authority_armed_v3(e.pilot_key,db_path=db_path))
    active=armed
    LOGGER.info(
        "v3 LIVE enrollment scan loaded=%d live=%d armed=%d candidates=%s",
        len(loaded), len(live), len(armed),
        ",".join(f"{e.strategy_key}:{'armed' if live_authority_armed_v3(e.pilot_key,db_path=db_path) else 'off'}" for e in live) or "none",
    )
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
    except Exception as exc:
        for e in enrollments:
            _record_runtime(e.pilot_key,"FAILED",f"{type(exc).__name__}: {exc}",db_path=db_path)
        raise
    # Saxo account endpoint returns JSON dictionaries, not account objects.
    # Treating them as attributes made every armed v3 cycle fail before execution.
    accounts={}
    account_currencies={}
    account_contexts={}
    for row in broker.accounts():
        if not isinstance(row,dict):
            continue
        account_id=str(row.get("AccountId") or "").strip()
        account_key=str(row.get("AccountKey") or "").strip()
        if account_id and account_key:
            accounts[account_id]=account_key
            account_currencies[account_id]=str(row.get('Currency') or '').upper()
            account_contexts[account_id]=(account_key,str(row.get('ClientKey') or ''))
    executed=0; end=now or datetime.now(timezone.utc)
    for e in enrollments:
        # Reconcile before computing a new signal: locks must be handled even
        # when market data is missing or the latest strategy target is HOLD.
        pending=pending_order_v3(account_id=e.account_id,uic=e.uic,
                                 asset_type=e.asset_type,db_path=db_path)
        if pending:
            # Keep reconciliation deliberately simple: Saxo's current exact
            # account/product inventory is the source of truth.  The durable
            # reservation records the inventory we expected after the POST.
            # If current inventory equals it, the mutation happened. Otherwise
            # keep the lock and wait; never resend an ambiguous order.
            expected=pending.get('expected_inventory')
            if expected is None:
                _record_runtime(e.pilot_key,'BLOCKED',
                    'Pending order lacks expected inventory; no retry sent',db_path=db_path)
                continue
            try:
                fresh_actual=_actual(e,broker)
                expected_amount=float(expected)
            except Exception as exc:
                LOGGER.error('v3 position verification unavailable pilot=%s error_type=%s',
                    e.pilot_key,type(exc).__name__)
                _record_runtime(e.pilot_key,'BLOCKED',
                    f'Position verification unavailable: {type(exc).__name__}',db_path=db_path)
                continue
            try:
                reconciliation=reconcile_position_v3(
                    expected_inventory=expected_amount,
                    submitted_amount=pending.get('submitted_amount'),
                    submitted_side=pending.get('submitted_side'),
                    actual_inventory=fresh_actual.amount)
            except (TypeError, ValueError):
                _record_runtime(e.pilot_key,'BLOCKED',
                    'Pending order lacks valid mutation evidence; no retry sent',db_path=db_path)
                continue
            if reconciliation.state=='CONFIRMED':
                mark_order_v3(request_key=pending['request_key'],state='RECONCILED',
                    detail='Exact Saxo inventory reached expected post-order position',
                    db_path=db_path)
                _record_runtime(e.pilot_key,'RECONCILED',
                    f'actual={fresh_actual.amount:g} expected={expected_amount:g} pending=confirmed; next cycle may evaluate target',
                    db_path=db_path)
            elif reconciliation.state=='WAIT':
                _record_runtime(e.pilot_key,'PENDING',
                    f'actual={fresh_actual.amount:g} expected={expected_amount:g} pending=waiting; no retry sent',
                    db_path=db_path)
            else:
                _record_runtime(e.pilot_key,'BLOCKED',
                    f'actual={fresh_actual.amount:g} expected={expected_amount:g} pending=conflict; manual/external inventory change requires acknowledgement',
                    db_path=db_path)
            continue
        actual=_actual(e,broker)
        _record_runtime(e.pilot_key,'READY',f'actual={actual.amount:g} pending=none; evaluating target',db_path=db_path)
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
        _record_runtime(e.pilot_key,'READY',
            f'actual={actual.amount:g} target={snapshot.risk_approved_target.amount:g} delta={snapshot.pending_delta:g} pending=none',
            db_path=db_path)
        mutation=next((s for s in plan.steps if s.action in {"OPEN","ADD","REDUCE","CLOSE"}),None)
        if mutation is None:
            _record_runtime(e.pilot_key,"MANAGING",f"target={snapshot.risk_approved_target.amount:g} actual={actual.amount:g}",db_path=db_path)
            continue
        # REDUCE/CLOSE may only shrink the exact observed position. OPEN/ADD use
        # the persisted submission-time NOK exposure policy below.
        if mutation.action in {'REDUCE','CLOSE'}:
            if actual.amount == 0 or mutation.amount > abs(actual.amount) + 1e-9:
                _record_runtime(e.pilot_key,'BLOCKED','Reduction exceeds exact current position',db_path=db_path)
                continue
            from decimal import Decimal, ROUND_DOWN
            requested=Decimal(str(mutation.amount)); permitted=requested.quantize(Decimal('0.01'),rounding=ROUND_DOWN)
            if permitted < Decimal('0.01'):
                _record_runtime(e.pilot_key,'BLOCKED','Reduction below 0.01 Saxo order step',db_path=db_path)
                continue
            if permitted != requested:
                from autotrader_v3_execution_plan_v1 import ExecutionStepV3
                mutation=ExecutionStepV3(mutation.action,float(permitted),mutation.direction,
                    mutation.requires_flat_confirmation,mutation.reason+'; floored to 0.01 Saxo order step')
        account=accounts.get(e.account_id)
        if account is None: raise RuntimeError(f"v3 LIVE account unavailable: {e.account_id}")
        side=("Buy" if mutation.direction=="LONG" else "Sell")
        if mutation.action in {"REDUCE","CLOSE"}: side=("Sell" if mutation.direction=="LONG" else "Buy")
        instrument=SaxoInstrument(asset=e.market_name,uic=int(e.uic),asset_type=e.asset_type)
        if mutation.action in {'OPEN','ADD'}:
            policy=load_execution_policy_v3(e.pilot_key,db_path=db_path)
            if policy is None:
                _record_runtime(e.pilot_key,'BLOCKED','OPEN/ADD requires an explicit V3 NOK exposure policy',db_path=db_path)
                continue
            try:
                capped=cap_open_add_amount_v3(broker=broker,account_key=account,
                    account_currency=account_currencies.get(e.account_id,''),instrument=instrument,
                    side=side,requested_amount=mutation.amount,policy=policy,
                    current_same_side_amount=abs(actual.amount) if mutation.action=='ADD' else 0.0)
            except Exception as exc:
                LOGGER.error('v3 OPEN/ADD sizing blocked pilot=%s error_type=%s',e.pilot_key,type(exc).__name__)
                _record_runtime(e.pilot_key,'BLOCKED',f'OPEN/ADD sizing unavailable: {type(exc).__name__}',db_path=db_path)
                continue
            if capped.permitted_amount + 1e-9 < mutation.amount:
                from autotrader_v3_execution_plan_v1 import ExecutionStepV3
                mutation=ExecutionStepV3(mutation.action,capped.permitted_amount,mutation.direction,
                    mutation.requires_flat_confirmation,mutation.reason+'; clamped by V3 NOK exposure cap')
            _record_runtime(e.pilot_key,'READY',
                f'actual={actual.amount:g} target={snapshot.risk_approved_target.amount:g} action={mutation.action} amount={mutation.amount:g} cap_nok={capped.max_notional_nok:g}',db_path=db_path)
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
