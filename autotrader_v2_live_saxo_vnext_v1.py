from __future__ import annotations

"""Small Saxo adapter for V2 vNext exact-boundary inventory and broker precheck."""

from dataclasses import dataclass
from typing import Any

from autotrader_saxo_net_position_direction_v2 import resolve_net_position_exposure_v2
from saxo_provider import SaxoInstrument
from saxo_trading import SaxoOrderRequest


@dataclass(frozen=True, slots=True)
class V2SaxoBoundaryStateV1:
    account_key: str
    account_currency: str
    signed_inventory: float


def _account_row(client, account_id: str) -> dict[str, Any]:
    payload = client._get("port/v1/accounts/me")
    rows = payload.get("Data") or []
    for row in rows if isinstance(rows, list) else ():
        if isinstance(row, dict) and str(row.get("AccountId") or "") == str(account_id):
            if not bool(row.get("Active", True)):
                raise RuntimeError("V2 Saxo account is inactive")
            return row
    raise RuntimeError("V2 Saxo account is unavailable")


def exact_boundary_state_v2_vnext_v1(client, *, account_id: str, uic: int, asset_type: str) -> V2SaxoBoundaryStateV1:
    account = _account_row(client, account_id)
    account_key = str(account.get("AccountKey") or "").strip()
    currency = str(account.get("Currency") or "").strip().upper()
    if not account_key or not currency:
        raise RuntimeError("V2 Saxo account lacks AccountKey/Currency")
    payload = client._get("port/v1/netpositions/me", params={"$top": 1000})
    rows = payload.get("Data") or []
    signed = 0.0
    for row in rows if isinstance(rows, list) else ():
        if not isinstance(row, dict):
            continue
        display = row.get("NetPositionView") if isinstance(row.get("NetPositionView"), dict) else {}
        dynamic = row.get("NetPositionDynamic") if isinstance(row.get("NetPositionDynamic"), dict) else {}
        static = row.get("NetPositionStatic") if isinstance(row.get("NetPositionStatic"), dict) else {}
        row_account = str(display.get("AccountId") or dynamic.get("AccountId") or static.get("AccountId") or row.get("AccountId") or "")
        row_uic = int(display.get("Uic") or dynamic.get("Uic") or static.get("Uic") or row.get("Uic") or -1)
        row_asset = str(display.get("AssetType") or dynamic.get("AssetType") or static.get("AssetType") or row.get("AssetType") or "")
        if row_account != str(account_id) or row_uic != int(uic) or row_asset != str(asset_type):
            continue
        exposure = resolve_net_position_exposure_v2(row)
        amount = float(exposure.amount)
        side = str(exposure.direction).strip().lower()
        signed += amount if side == "buy" else -amount
    return V2SaxoBoundaryStateV1(account_key, currency, signed)


def broker_precheck_v2_vnext_v1(client, *, account_key: str, market_name: str, uic: int, asset_type: str, amount: float, side: str, external_reference: str) -> tuple[SaxoOrderRequest, dict[str, Any]]:
    instrument = SaxoInstrument(asset=str(market_name), uic=int(uic), asset_type=str(asset_type))
    order = SaxoOrderRequest(
        account_key=str(account_key), instrument=instrument, amount=float(amount),
        buy_sell=str(side), external_reference=str(external_reference)[-50:])
    precheck = client.precheck(order)
    result = str(precheck.get("PreCheckResult") or precheck.get("Result") or "").strip().lower()
    if result not in {"ok", "passed", "success"}:
        raise RuntimeError(f"V2 Saxo precheck rejected: {result or 'missing result'}")
    return order, precheck
