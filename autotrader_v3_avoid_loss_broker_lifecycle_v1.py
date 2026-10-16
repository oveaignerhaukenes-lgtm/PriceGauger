"""Pure broker-evidence gates for Avoid Loss V1 OPEN and broker FLAT.

These functions neither query Saxo nor mutate order guard, risk tables,
strategy settings, or Saxo. Input must come from separately account-scoped
broker GETs and a durable V3 ledger checked by the caller. A "verified"
result cannot substitute for real fill/restart/timeout testing.
"""
from __future__ import annotations

from math import isfinite
from typing import Mapping, Sequence

from autotrader_v3_avoid_loss_v1 import ConfirmedPositionV1


def _num(value, label: str) -> float:
    if value is None or isinstance(value, bool):
        raise ValueError(label+" absent")
    try:
        number = float(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(label+" invalid") from exc
    if not isfinite(number):
        raise ValueError(label+" nonfinite")
    return number


def require_confirmed_final_fill_v1(
    *,
    activity: Mapping,
    expected_side: str,
    expected_amount: float,
    expected_position_id: str,
) -> None:
    """Saxo audit Fill is NOT sufficient: only FinalFill + Confirmed.

    This method assumes the broker adapter already verified AccountKey,
    OrderId, Uic and AssetType. An unverifiable/partial fill always blocks.
    """
    if not isinstance(activity, Mapping) or activity.get("available") is not True:
        raise ValueError("order activity unavailable")
    if str(activity.get("status") or "").lower() != "finalfill":
        raise ValueError("Saxo order not FinalFill")
    if str(activity.get("sub_status") or "").lower() != "confirmed":
        raise ValueError("Saxo FinalFill not Confirmed")
    if expected_side not in {"Buy","Sell"} or str(activity.get("side") or "").lower()!=expected_side.lower():
        raise ValueError("Saxo order side mismatch")
    if str(activity.get("position_id") or "") != str(expected_position_id or "") or not expected_position_id:
        raise ValueError("Saxo order PositionId mismatch")
    expected=_num(expected_amount,"expected fill amount")
    filled=_num(activity.get("filled_amount"),"Saxo filled amount")
    if expected<=0 or abs(filled-expected)>1e-9:
        raise ValueError("Saxo exact full fill amount mismatch")


def validated_confirmed_open_anchor_v1(
    *,
    account_id: str,
    uic: int,
    asset_type: str,
    durable_entry: Mapping,
    audit_activity: Mapping,
    individual_position: Mapping,
    signed_net_inventory: float,
) -> ConfirmedPositionV1:
    """Validate provenance of a *new* one-tranche OPEN before margin anchor.

    durable_entry must be a single frozen preflight row with a RECONCILED
    V3 request and known broker order id. Never use a prior/manual position
    or reconstruct initial margin from current account exposure.
    """
    if not str(account_id).strip() or not str(asset_type).strip() or int(uic)<=0:
        raise ValueError("account/product boundary absent")
    if not isinstance(durable_entry,Mapping) or not isinstance(individual_position,Mapping):
        raise ValueError("durable entry or exact position absent")
    if durable_entry.get("guard_state")!="RECONCILED":
        raise ValueError("V3 durable OPEN is not reconciled")
    if not str(durable_entry.get("request_key") or "").strip() or not str(durable_entry.get("broker_order_id") or "").strip():
        raise ValueError("durable OPEN request identity unavailable")
    for key,want in (("account_id",account_id),("uic",int(uic)),("asset_type",asset_type)):
        if key not in durable_entry or str(durable_entry[key])!=str(want):
            raise ValueError("durable OPEN account/product mismatch")
    signed=_num(signed_net_inventory,"broker signed inventory")
    staged=_num(durable_entry.get("signed_amount"),"staged signed amount")
    submitted=_num(durable_entry.get("submitted_amount"),"submitted amount")
    expected=_num(durable_entry.get("expected_inventory"),"expected net inventory")
    margin=_num(durable_entry.get("initial_margin_nok"),"frozen initial margin in NOK")
    if (signed==0 or margin<=0 or submitted<=0
        or abs(signed-staged)>1e-9 or abs(signed-expected)>1e-9
        or abs(abs(signed)-submitted)>1e-9):
        raise ValueError("Saxo broker inventory differs from durable one-tranche OPEN")
    side="Buy" if signed>0 else "Sell"
    if str(durable_entry.get("submitted_side") or "")!=side:
        raise ValueError("durable opening direction mismatch")
    posid=str(individual_position.get("PositionId") or "").strip()
    base=individual_position.get("PositionBase")
    if not posid or not isinstance(base,Mapping):
        raise ValueError("individual PositionId/Base unavailable")
    if (str(base.get("AccountId") or base.get("PositionsAccount") or "")!=account_id
        or int(base.get("Uic") or -1)!=int(uic)
        or str(base.get("AssetType") or "")!=asset_type):
        raise ValueError("individual position account/product mismatch")
    if str(base.get("Status") or "").lower() not in {"open","partiallyclosed"}:
        raise ValueError("individual position is not open")
    amount=_num(base.get("Amount"),"individual position amount")
    if amount==0 or abs(abs(amount)-abs(signed))>1e-9:
        raise ValueError("individual position size mismatch")
    require_confirmed_final_fill_v1(
        activity=audit_activity,expected_side=side,
        expected_amount=abs(signed),expected_position_id=posid)
    return ConfirmedPositionV1(
        account_id=account_id,uic=int(uic),asset_type=asset_type,
        position_token=posid,signed_amount=signed,entry_margin_nok=margin)


def require_broker_confirmed_flat_v1(
    *,
    account_scoped_net_rows: Sequence,
    account_scoped_individual_rows: Sequence,
    unresolved_order: bool,
) -> None:
    """Fail closed until both distinct broker queries show no exposure.

    Caller must ensure reads are the same exact account/product and current;
    the order guard must have no unresolved order. Does not erase any anchor,
    issue any CLOSE, or assert that an order filled at a target price.
    """
    if unresolved_order is not False:
        raise ValueError("order status unresolved")
    if account_scoped_net_rows is None or account_scoped_individual_rows is None:
        raise ValueError("broker FLAT evidence not available")
    if len(account_scoped_net_rows)!=0 or len(account_scoped_individual_rows)!=0:
        raise ValueError("broker position still exists or has ambiguous zero-net hedge")


__all__=[
    "require_confirmed_final_fill_v1",
    "validated_confirmed_open_anchor_v1",
    "require_broker_confirmed_flat_v1",
]
