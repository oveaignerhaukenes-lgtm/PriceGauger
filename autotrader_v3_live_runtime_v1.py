from __future__ import annotations
import logging
from uuid import uuid5, NAMESPACE_URL
from datetime import datetime,timedelta,timezone
from autotrader_mtf_entry_shadow_v2 import closed_bars_v2,macd_observations_v2
from autotrader_engine_account_ownership_v1 import ENGINE_V3, load_account_owner_v1
from autotrader_v3_runtime_instances_v1 import load_v3_runtime_instances_v1
from autotrader_v3_strategy_registry_v1 import STRATEGIES_V3, evaluate_strategy_bar_v3
from autotrader_v3_closed_bar_driver_v1 import ensure_closed_bar_driver_schema_v3
from autotrader_v3_domain import AccountBoundaryV3,ControlModeV3,TargetInventoryV3,signed_inventory_v3
from autotrader_v3_execution_plan_v1 import plan_execution_v3
from autotrader_v3_live_authority_v1 import live_authority_armed_v3
from autotrader_v3_legacy_ownership_migration_v1 import backfill_legacy_v3_live_ownership_v1
from autotrader_v3_order_guard_v1 import reserve as reserve_order_v3, mark as mark_order_v3, unresolved as unresolved_order_v3, pending_order as pending_order_v3
from database import connect,using_postgres
from autotrader_v3_live_saxo_v1 import configured_live_pilot_client_v3
from autotrader_v3_macd_histogram_v1 import STRATEGY_KEY_V3
from autotrader_v3_macd_trailing_v1 import STRATEGY_KEY_V3 as TRAILING_KEY
from autotrader_v3_pipeline_v1 import TraderV3,evaluate_trader_v3
from autotrader_v3_config_v1 import load_autotrader_config_v3
from autotrader_v3_registry_v1 import fixed_timeframe_minutes_v3, live_config_issues_v3
from autotrader_v3_reset_on_loss_v1 import ResetOnLossModifierV3
from autotrader_v3_position_reconcile_v1 import reconcile_position_v3
from autotrader_v3_execution_policy_v1 import load_execution_policy_v3
from autotrader_v3_live_sizing_v1 import cap_open_add_amount_v3, enforce_execution_policy_precheck_v3
from autotrader_open_sizing_v2 import load_entry_instrument_rules_v2
from autotrader_v3_strategy_sizing_v1 import strategy_amount_config_v3
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from saxo_provider import SaxoInstrument
from saxo_trading import SaxoOrderRequest

LOGGER=logging.getLogger("pricegauger.autotrader.v3.live")

def _live_timeframe_minutes_v3(timeframe:str)->int:
    label=str(timeframe or "").strip()
    if label=="Adaptiv":
        raise ValueError("Adaptiv timeframe is not implemented in V3 LIVE")
    try:
        return fixed_timeframe_minutes_v3(label)
    except ValueError as exc:
        raise ValueError(f"Unsupported V3 LIVE timeframe: {label or '<empty>'}") from exc

def _prepare_live_decision_context_v3(*,trader_id:str,strategy_key:str,
                                      timeframe_minutes:int,db_path="pricegauger.db")->bool:
    """Keep closed-bar impulse history from leaking across strategy/timeframe changes.

    Before this fix V3 LIVE was hard-coded to 5m. Existing rows therefore have an
    implicit 5m context. On the first configured non-5m cycle we preserve the current
    target and last processed bar, but clear previous_spread so a 5m impulse cannot
    become the previous observation for a 15m/30m/etc decision.
    """
    ensure_closed_bar_driver_schema_v3(db_path)
    with connect(db_path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS autotrader_v3_live_decision_context(
          trader_id TEXT PRIMARY KEY,
          strategy_key TEXT NOT NULL,
          timeframe_minutes INTEGER NOT NULL,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        row=db.execute(
            "SELECT strategy_key,timeframe_minutes FROM autotrader_v3_live_decision_context WHERE trader_id=?",
            (str(trader_id),),
        ).fetchone()
        if row is None:
            previous_strategy=str(strategy_key)
            previous_timeframe=5
        else:
            previous_strategy=str(row["strategy_key"] if isinstance(row,dict) else row[0])
            previous_timeframe=int(row["timeframe_minutes"] if isinstance(row,dict) else row[1])
        changed=(previous_strategy!=str(strategy_key) or previous_timeframe!=int(timeframe_minutes))
        if changed:
            db.execute(
                "UPDATE autotrader_v3_closed_bar_state SET previous_spread=NULL WHERE trader_id=?",
                (str(trader_id),),
            )
        db.execute("""INSERT INTO autotrader_v3_live_decision_context(
          trader_id,strategy_key,timeframe_minutes,updated_at)
          VALUES(?,?,?,CURRENT_TIMESTAMP)
          ON CONFLICT(trader_id) DO UPDATE SET
            strategy_key=excluded.strategy_key,
            timeframe_minutes=excluded.timeframe_minutes,
            updated_at=CURRENT_TIMESTAMP""",
            (str(trader_id),str(strategy_key),int(timeframe_minutes)))
    return changed

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

def _load_owned_armed_runtime_instances_v3(*,db_path="pricegauger.db"):
    """Return only enabled V3 instances with explicit LIVE authority and exact account ownership."""
    active=[]
    instances=load_v3_runtime_instances_v1(db_path=db_path)
    LOGGER.info("v3 LIVE discovered enabled instances=%d ids=%s",
        len(instances),",".join(e.pilot_key for e in instances) or "-")
    if using_postgres():
        try:
            claimed=backfill_legacy_v3_live_ownership_v1(instances,db_path=db_path)
            if claimed:
                LOGGER.info("v3 LIVE legacy ownership backfilled instances=%s",",".join(claimed))
        except Exception as exc:
            detail=f"V3 legacy ownership migration blocked: {type(exc).__name__}: {exc}"
            LOGGER.error("%s",detail)
            for e in instances:
                if live_authority_armed_v3(e.pilot_key,db_path=db_path):
                    _record_runtime(e.pilot_key,"BLOCKED",detail+"; no orders sent.",db_path=db_path)
            return ()
    for e in instances:
        armed=live_authority_armed_v3(e.pilot_key,db_path=db_path)
        LOGGER.info("v3 LIVE candidate instance=%s armed=%s",e.pilot_key,armed)
        if not armed:
            continue
        owner=load_account_owner_v1(e.account_id,db_path=db_path)
        if owner is None or owner.engine_id != ENGINE_V3 or owner.owner_key != e.pilot_key:
            observed="unowned" if owner is None else f"{owner.engine_id}/{owner.owner_key}"
            _record_runtime(e.pilot_key,"BLOCKED",
                f"V3 account ownership mismatch: expected {ENGINE_V3}/{e.pilot_key}, got {observed}; no orders sent.",
                db_path=db_path)
            continue
        active.append(e)
    return tuple(active)

def run_v3_live_cycle_v1(*,db_path="pricegauger.db",now=None)->int:
    """Normal v3 LIVE runtime. The LIVE toggle plus exact V3 account ownership is the authority boundary."""
    active=_load_owned_armed_runtime_instances_v3(db_path=db_path)
    LOGGER.info("v3 LIVE active owned armed instances=%d",len(active))
    enrollments=[]
    for e in active:
        config = load_autotrader_config_v3(e.pilot_key, db_path=db_path)
        issues = live_config_issues_v3(
            strategy_key=config.strategy_key,
            timeframe=config.timeframe,
            control_mode=config.control_mode,
            modifiers=config.modifiers,
        )
        if issues:
            _record_runtime(
                e.pilot_key,
                "BLOCKED",
                "V3 LIVE config unsupported: " + "; ".join(issues) + "; no orders sent.",
                db_path=db_path,
            )
            continue
        adapter = STRATEGIES_V3.get(e.strategy_key)
        if adapter is None:
            _record_runtime(e.pilot_key, "BLOCKED",
                f"Unregistered V3 strategy {e.strategy_key}; no orders sent.", db_path=db_path)
            continue
        if not adapter.live_route_enabled:
            _record_runtime(e.pilot_key, "BLOCKED",
                f"{e.strategy_key}: LIVE execution/reconciliation not validated. No orders sent.",
                db_path=db_path)
            continue
        enrollments.append(e)
    enrollments=tuple(enrollments)
    if not enrollments: return 0
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
        pending=pending_order_v3(account_id=e.account_id,uic=e.uic,
                                 asset_type=e.asset_type,db_path=db_path)
        if pending:
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
                # LIVE authority is ownership of this exact account+instrument.
                # Saxo actual is therefore adopted even when a human changed the
                # position while V3 had an older expectation. Retire the stale
                # request; the next cycle manages the full actual inventory.
                # This does not authorize expansion: OPEN/ADD still passes through
                # the configured V3 exposure policy, while REDUCE/CLOSE may manage
                # an oversized adopted position back toward the strategy target.
                mark_order_v3(request_key=pending['request_key'],state='RECONCILED',
                    detail='LIVE account+instrument inventory adopted; stale V3 expectation retired',
                    db_path=db_path)
                _record_runtime(e.pilot_key,'RECONCILED',
                    f'actual={fresh_actual.amount:g} expected={expected_amount:g} pending=inventory-adopted; next cycle may manage actual',
                    db_path=db_path)
            continue
        actual=_actual(e,broker)
        config=load_autotrader_config_v3(e.pilot_key,db_path=db_path)
        try:
            timeframe_minutes=_live_timeframe_minutes_v3(config.timeframe)
        except ValueError as exc:
            _record_runtime(e.pilot_key,'BLOCKED',f'{exc}; no orders sent',db_path=db_path)
            continue
        account=accounts.get(e.account_id)
        if account is None:
            _record_runtime(e.pilot_key,'BLOCKED',f'V3 LIVE account unavailable: {e.account_id}',db_path=db_path)
            continue
        instrument=SaxoInstrument(asset=e.market_name,uic=int(e.uic),asset_type=e.asset_type)
        try:
            instrument_rules=load_entry_instrument_rules_v2(
                broker.client,account_key=account,instrument=instrument)
            strategy_amount_config=strategy_amount_config_v3(
                strategy_key=e.strategy_key,rules=instrument_rules)
        except Exception as exc:
            _record_runtime(
                e.pilot_key,'BLOCKED',
                f'V3 instrument strategy sizing unavailable: {type(exc).__name__}: {exc}',
                db_path=db_path)
            continue
        context_changed=_prepare_live_decision_context_v3(
            trader_id=e.pilot_key,strategy_key=e.strategy_key,
            timeframe_minutes=timeframe_minutes,db_path=db_path)
        if context_changed:
            LOGGER.info("v3 LIVE decision context changed trader=%s strategy=%s timeframe=%s",
                e.pilot_key,e.strategy_key,config.timeframe)
        _record_runtime(e.pilot_key,'READY',
            f'actual={actual.amount:g} pending=none; evaluating target timeframe={config.timeframe}',
            db_path=db_path)
        bars=CanonicalMarketBarStoreV2(db_path).load_instrument_range(
            instrument_id=e.instrument_id,start=end-timedelta(days=14),end=end,limit=20000)
        closed=closed_bars_v2(tuple(b.point for b in bars),market=e.market_name,
            timeframe_minutes=timeframe_minutes) if bars else ()
        obs=macd_observations_v2(closed,timeframe_minutes=timeframe_minutes) if closed else ()
        if not obs:
            _record_runtime(e.pilot_key,"DEGRADED",
                f"no closed {config.timeframe} MACD observation",db_path=db_path)
            continue
        decision=evaluate_strategy_bar_v3(
            trader_id=e.pilot_key,observation=obs[-1],bars=closed,
            strategy_key=e.strategy_key,config=strategy_amount_config,db_path=db_path)
        trader=TraderV3(
            e.pilot_key,
            AccountBoundaryV3(e.account_id,int(e.uic),e.asset_type),
            e.strategy_key,
            mode=ControlModeV3.DETERMINISTIC,  # canonical mapping for UI control_mode="Manuell"
        )
        modifiers=[]
        if 'reset-on-loss' in config.modifiers:
            if abs(actual.amount) <= 1e-12:
                modifiers.append(ResetOnLossModifierV3(open_pnl=0.0,actual_inventory=actual.amount))
            else:
                try:
                    open_pnl=broker.open_pnl_exact(account_id=e.account_id,uic=int(e.uic),asset_type=e.asset_type)
                except Exception as exc:
                    LOGGER.warning("v3 Reset on Loss skipped pilot=%s: P/L unavailable: %s", e.pilot_key, type(exc).__name__)
                else:
                    modifiers.append(ResetOnLossModifierV3(open_pnl=open_pnl,actual_inventory=actual.amount))
        snapshot=evaluate_trader_v3(trader=trader,base_target=decision.decision.target,actual_inventory=actual,modifiers=tuple(modifiers)).snapshot
        plan=plan_execution_v3(snapshot)
        _record_runtime(e.pilot_key,'READY',
            f'actual={actual.amount:g} target={snapshot.risk_approved_target.amount:g} delta={snapshot.pending_delta:g} timeframe={config.timeframe} pending=none',
            db_path=db_path)
        mutation=next((s for s in plan.steps if s.action in {"OPEN","ADD","REDUCE","CLOSE"}),None)
        if mutation is None:
            _record_runtime(e.pilot_key,"MANAGING",f"target={snapshot.risk_approved_target.amount:g} actual={actual.amount:g}",db_path=db_path)
            continue
        if mutation.action in {'REDUCE','CLOSE'}:
            if actual.amount == 0 or mutation.amount > abs(actual.amount) + 1e-9:
                _record_runtime(e.pilot_key,'BLOCKED','Reduction exceeds exact current position',db_path=db_path)
                continue
            from decimal import Decimal, ROUND_DOWN
            step=Decimal(str(instrument_rules.increment_size))
            if step <= 0:
                _record_runtime(e.pilot_key,'BLOCKED','Saxo amount step is not positive',db_path=db_path)
                continue
            requested=Decimal(str(mutation.amount))
            nearest_steps=(requested / step).quantize(Decimal('1'))
            nearest=nearest_steps * step
            if abs(requested-nearest) <= Decimal('0.000000001'):
                requested=nearest
            permitted=(requested / step).to_integral_value(rounding=ROUND_DOWN) * step
            if permitted <= 0:
                _record_runtime(
                    e.pilot_key,'BLOCKED',
                    f'Reduction below Saxo amount step {float(step):g}',db_path=db_path)
                continue
            if permitted != requested:
                from autotrader_v3_execution_plan_v1 import ExecutionStepV3
                mutation=ExecutionStepV3.from_amount(
                    mutation.action,float(permitted),mutation.direction,
                    mutation.requires_flat_confirmation,
                    mutation.reason+f'; floored to Saxo amount step {float(step):g}')
        side=("Buy" if mutation.direction=="LONG" else "Sell")
        if mutation.action in {"REDUCE","CLOSE"}: side=("Sell" if mutation.direction=="LONG" else "Buy")
        policy=None
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
                reason=str(exc).strip() if isinstance(exc,ValueError) else ''
                LOGGER.error('v3 OPEN/ADD sizing blocked pilot=%s error_type=%s reason=%s',e.pilot_key,type(exc).__name__,reason or 'unavailable')
                detail=f'OPEN/ADD sizing unavailable: {type(exc).__name__}'
                if reason:
                    detail += f' ({reason})'
                _record_runtime(e.pilot_key,'BLOCKED',detail,db_path=db_path)
                continue
            if capped.permitted_amount + 1e-9 < mutation.amount:
                from autotrader_v3_execution_plan_v1 import ExecutionStepV3
                mutation=ExecutionStepV3.from_amount(
                    mutation.action,capped.permitted_amount,mutation.direction,
                    mutation.requires_flat_confirmation,mutation.reason+'; aligned to Saxo amount step')
            _record_runtime(e.pilot_key,'READY',
                f'actual={actual.amount:g} target={snapshot.risk_approved_target.amount:g} action={mutation.action} amount={mutation.amount:g} cap_nok={capped.max_notional_nok:g}',db_path=db_path)
        signed_delta=mutation.amount if side=='Buy' else -mutation.amount
        request_key=str(uuid5(NAMESPACE_URL,
            f'{e.pilot_key}:{decision.decision_key}:{mutation.action}:{side}:'
            f'{actual.amount:.10g}:{mutation.amount:.10g}'))
        order=SaxoOrderRequest(account_key=account,instrument=instrument,amount=mutation.amount,buy_sell=side,
            external_reference=('pgv3-'+request_key)[-50:])
        pre=broker.precheck(order)
        if str(pre.get("PreCheckResult") or pre.get("Result") or "").lower() not in {"ok","passed","success"}:
            raise RuntimeError(f"v3 LIVE precheck rejected: {pre}")
        if mutation.action in {'OPEN','ADD'}:
            try:
                capital_required=enforce_execution_policy_precheck_v3(
                    precheck=pre,side=side,
                    account_currency=account_currencies.get(e.account_id,''),
                    policy=policy)
            except Exception as exc:
                _record_runtime(
                    e.pilot_key,'BLOCKED',
                    f'V3 capital policy blocked {mutation.action}: {type(exc).__name__}: {exc}',
                    db_path=db_path)
                continue
            _record_runtime(
                e.pilot_key,'READY',
                f'actual={actual.amount:g} target={snapshot.risk_approved_target.amount:g} '
                f'action={mutation.action} amount={mutation.amount:g} '
                f'capital_required_nok={capital_required:g} cap_nok={policy.max_notional_nok:g}',
                db_path=db_path)
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