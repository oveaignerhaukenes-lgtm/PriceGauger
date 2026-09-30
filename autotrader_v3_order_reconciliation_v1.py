"""Conservative V3 order reconciliation: confirmed fill AND fresh exact inventory."""
from __future__ import annotations
from math import isclose,isfinite


class V3ReconciliationPhaseError(RuntimeError):
    """Sanitized phase-only error; never persist broker payloads or credentials."""

    def __init__(self, phase: str, original: Exception):
        self.phase = phase
        self.cause_type = type(original).__name__
        # Only our own enumerated audit reasons may be surfaced to runtime/UI.
        self.reason = (str(original) if isinstance(original, V3AuditIncompleteError)
                       and str(original) in ('invalid_data','page_limit','next_page') else '')
        suffix = f': {self.reason}' if self.reason else ''
        super().__init__(f"{phase}: {self.cause_type}{suffix}")

from autotrader_v3_order_audit_v1 import verified_order_fills_v3,fetch_exact_order_audit_v3,V3AuditIncompleteError
from autotrader_v3_domain import signed_inventory_v3


def verified_reconciled_inventory_v3(*,pending,rows,observations,account_id,uic,asset_type):
    """Return True only if independent fill evidence and exact fresh inventory agree.

    Partial fills, missing order identifiers, ambiguous positions, stale legacy
    reservations and wrong account/product never release the lock.
    """
    broker_id=pending.get('broker_order_id')
    expected=pending.get('expected_inventory')
    requested=pending.get('submitted_amount')
    side=pending.get('submitted_side')
    if not broker_id or expected is None or requested is None or side not in ('Buy','Sell'):
        return False
    filled=verified_order_fills_v3(rows,account_id=account_id,uic=uic,
                                asset_type=asset_type,order_id=broker_id,side=side)
    if filled is None:
        return False
    try:
        quantity=float(filled)
        requested=float(requested)
        expected=float(expected)
        if not all(isfinite(x) for x in (quantity,requested,expected)) or requested<=0:
            return False
        if not isclose(quantity,requested,rel_tol=0,abs_tol=1e-8):
            return False
        matches=[o for o in observations if o.account_id==account_id
                 and int(o.uic)==int(uic) and o.asset_type==asset_type]
        if len(matches)>1:
            return False
        actual=0.0 if not matches else signed_inventory_v3(
            direction=matches[0].direction,amount=matches[0].amount).amount
        return isclose(actual,expected,rel_tol=0,abs_tol=1e-8)
    except (TypeError,ValueError,AttributeError):
        return False


def reconcile_pending_v3(*,broker,pending,account_id,uic,asset_type,
                          account_key,client_key,read_positions,mark_reconciled,db_path):
    """Never mark terminal without independently refreshed Saxo positions."""
    if not client_key or not pending.get('broker_order_id'):
        return False
    try:
        rows=fetch_exact_order_audit_v3(broker,account_key=account_key,client_key=client_key)
    except Exception as exc:
        raise V3ReconciliationPhaseError('audit_fetch', exc) from exc
    # This must be a fresh broker read after audit, not a cached cycle snapshot.
    try:
        observations=read_positions(broker.client)
    except Exception as exc:
        raise V3ReconciliationPhaseError('fresh_position_read', exc) from exc
    try:
        verified=verified_reconciled_inventory_v3(pending=pending,rows=rows,
            observations=observations,account_id=account_id,uic=uic,asset_type=asset_type)
    except Exception as exc:
        raise V3ReconciliationPhaseError('fill_inventory_verify', exc) from exc
    if not verified:
        return False
    try:
        mark_reconciled(request_key=pending['request_key'],state='RECONCILED',db_path=db_path)
    except Exception as exc:
        raise V3ReconciliationPhaseError('persist_reconciled', exc) from exc
    return True
