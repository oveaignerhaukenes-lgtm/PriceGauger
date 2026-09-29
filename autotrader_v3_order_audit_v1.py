"""Read-only Saxo audit verification for unresolved V3 orders.

A FinalFill is evidence of a fill, not by itself proof that inventory matches
our target. This module deliberately never releases a durable order lock.
"""
from __future__ import annotations
from datetime import datetime,timedelta,timezone


def verified_final_fill_v3(rows, *, account_id, uic, asset_type, order_id):
    """Require exactly one confirmed, exact-boundary audit record."""
    if not order_id:
        return None
    matches=[]
    for row in rows:
        if not isinstance(row,dict):
            continue
        if (str(row.get('OrderId') or '')!=str(order_id)
            or str(row.get('AccountId') or '')!=str(account_id)
            or str(row.get('AssetType') or '')!=str(asset_type)
            or str(row.get('Status') or '')!='FinalFill'
            or str(row.get('SubStatus') or '') not in ('','Confirmed')):
            continue
        try:
            if int(row.get('Uic')) != int(uic):
                continue
            if float(row.get('FilledAmount') or row.get('Amount') or 0)<=0:
                continue
        except (ValueError,TypeError):
            continue
        matches.append(row)
    return matches[0] if len(matches)==1 else None


def fetch_exact_order_audit_v3(broker, *, account_key, client_key, since=None, now=None):
    """Read-only audit fetch; never treat missing/truncated pages as confirmation."""
    end=now or datetime.now(timezone.utc)
    start=since or end-timedelta(days=2)
    payload=broker.client._get('cs/v1/audit/orderactivities',params={
        'AccountKey':account_key,'ClientKey':client_key,'EntryType':'All',
        'FromDateTime':start.isoformat().replace('+00:00','Z'),
        'ToDateTime':end.isoformat().replace('+00:00','Z'),'$top':500})
    rows=payload.get('Data')
    if not isinstance(rows,list) or len(rows)>=500 or payload.get('__next') or payload.get('Next'):
        raise RuntimeError('Saxo audit incomplete: cannot reconcile order')
    return rows
