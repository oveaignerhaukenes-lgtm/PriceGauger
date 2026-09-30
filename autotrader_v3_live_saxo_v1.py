from __future__ import annotations
from dataclasses import dataclass
from saxo_provider import LIVE_BASE_URL,SaxoClient,SaxoInstrument,SaxoError,configured_client
from saxo_trading import SaxoOrderRequest,SaxoTradingSafetyError

class SaxoLivePilotClientV3:
    """Narrow LIVE adapter. Construction and every POST fail closed unless explicitly confirmed."""
    def __init__(self, client:SaxoClient):
        if client.base_url.rstrip("/").lower()!=LIVE_BASE_URL.lower():
            raise SaxoTradingSafetyError("v3 LIVE pilot requires Saxo LIVE endpoint")
        self.client=client
    def accounts(self):
        payload=self.client._get("port/v1/accounts/me"); return tuple(payload.get("Data") or ())
    def precheck(self, order:SaxoOrderRequest):
        return self._post("trade/v2/orders/precheck",order.payload())
    def place_order(self, order:SaxoOrderRequest, *, confirm_live:bool=False):
        if not confirm_live: raise SaxoTradingSafetyError("v3 LIVE order requires explicit confirm_live=True")
        return self._post("trade/v2/orders",order.payload())
    def net_positions_exact(self, *,account_id:str,uic:int,asset_type:str):
        payload=self.client._get("port/v1/netpositions/me",params={"$top":1000}); matches=[]
        for row in payload.get("Data") or []:
            if not isinstance(row,dict): continue
            base=row.get("NetPositionBase") if isinstance(row.get("NetPositionBase"),dict) else {}
            if int(base.get("Uic") or -1)!=int(uic) or str(base.get("AssetType") or "")!=str(asset_type): continue
            aid=str(base.get("PositionsAccount") or base.get("AccountId") or "")
            if not aid: raise SaxoTradingSafetyError("v3 LIVE position missing exact account identity")
            if aid!=str(account_id): continue
            matches.append(row)
        if len(matches)>1: raise SaxoTradingSafetyError("ambiguous v3 LIVE exact-boundary position state")
        return tuple(matches)
    def signed_inventory_exact(self, *,account_id:str,uic:int,asset_type:str)->float:
        """Return signed inventory for one exact V3 account/product boundary."""
        rows=self.net_positions_exact(account_id=account_id,uic=uic,asset_type=asset_type)
        if not rows:
            return 0.0
        base=rows[0].get("NetPositionBase") or {}
        has_long=base.get("AmountLong") is not None
        has_short=base.get("AmountShort") is not None
        if has_long or has_short:
            long_amount=float(base.get("AmountLong") or 0.0)
            short_amount=float(base.get("AmountShort") or 0.0)
            if long_amount < 0 or short_amount < 0:
                raise SaxoTradingSafetyError("v3 LIVE position has negative gross amount")
            return long_amount-short_amount
        amount=float(base.get("Amount") or 0.0)
        direction=str(base.get("OpeningDirection") or "").strip().lower()
        if abs(amount)<=1e-12:
            return 0.0
        if direction=="buy":
            return abs(amount)
        if direction=="sell":
            return -abs(amount)
        raise SaxoTradingSafetyError("v3 LIVE position lacks direction authority")
    def _post(self,path,payload):
        self.client._set_authorization()
        response=self.client.session.post(f"{self.client.base_url}/{path}",json=payload,timeout=self.client.timeout)
        try: body=response.json()
        except ValueError as exc: raise SaxoError("LIVE response was not JSON",status="INVALID_RESPONSE",status_code=response.status_code) from exc
        if not response.ok: raise SaxoError(str(body),status="REQUEST_FAILED",status_code=response.status_code)
        if not isinstance(body,dict): raise SaxoError("LIVE response was not an object",status="INVALID_RESPONSE")
        return body

def configured_live_pilot_client_v3():
    client=configured_client()
    if client is None or client.base_url.rstrip("/").lower()!=LIVE_BASE_URL.lower(): return None
    return SaxoLivePilotClientV3(client)
