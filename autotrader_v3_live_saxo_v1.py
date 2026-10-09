from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping
from saxo_provider import LIVE_BASE_URL,SaxoClient,SaxoInstrument,SaxoError,configured_client
from saxo_trading import SaxoOrderRequest,SaxoTradingSafetyError

@dataclass(frozen=True, slots=True)
class SaxoMarketStatusV3:
    is_open: bool | None
    market_state: str | None
    quote_error: str | None

class SaxoLivePilotClientV3:
    """Narrow LIVE adapter. Construction and every POST fail closed unless explicitly confirmed."""
    def __init__(self, client:SaxoClient):
        if client.base_url.rstrip("/").lower()!=LIVE_BASE_URL.lower():
            raise SaxoTradingSafetyError("v3 LIVE pilot requires Saxo LIVE endpoint")
        self.client=client
    def accounts(self):
        payload=self.client._get("port/v1/accounts/me"); return tuple(payload.get("Data") or ())
    def precheck(self, order:SaxoOrderRequest):
        payload=order.payload()
        payload["FieldGroups"]=["MarginImpactBuySell","Costs"]
        return self._post("trade/v2/orders/precheck",payload)
    def place_order(self, order:SaxoOrderRequest, *, confirm_live:bool=False):
        if not confirm_live: raise SaxoTradingSafetyError("v3 LIVE order requires explicit confirm_live=True")
        return self._post("trade/v2/orders",order.payload())
    def _account_context_exact(self, account_id:str):
        matches=[]
        for row in self.accounts():
            if not isinstance(row,dict):
                continue
            if str(row.get("AccountId") or "").strip()!=str(account_id):
                continue
            account_key=str(row.get("AccountKey") or "").strip()
            client_key=str(row.get("ClientKey") or "").strip()
            if not account_key:
                raise SaxoTradingSafetyError("v3 LIVE account lacks AccountKey")
            matches.append((account_key,client_key))
        if len(matches)!=1:
            raise SaxoTradingSafetyError("v3 LIVE account identity is missing or ambiguous")
        return matches[0]
    def order_activity_exact(self, *,account_id:str,order_id:str,uic:int,asset_type:str):
        """Read the broker's historical LAST order activity for one exact Saxo boundary.

        A missing activity is UNKNOWN, never evidence of cancellation.  This
        method neither submits nor mutates orders and never authorizes retries.
        Saxo: GET /cs/v1/audit/orderactivities?AccountKey=...&OrderId=...&
              EntryType=Last (Personal:Read).
        """
        identity=str(account_id or '').strip()
        order=str(order_id or '').strip()
        if not identity or not order:
            raise SaxoTradingSafetyError("order activity requires exact account and OrderId")
        account_key,_=self._account_context_exact(identity)
        body=self.client._get("cs/v1/audit/orderactivities",params={
            "AccountKey":account_key,"OrderId":order,"EntryType":"Last","$top":20,
        })
        if not isinstance(body,Mapping) or body.get("__next"):
            raise SaxoTradingSafetyError("Saxo order audit response missing or incomplete")
        entries=body.get("Data")
        if not isinstance(entries,list):
            raise SaxoTradingSafetyError("Saxo order audit Data missing")
        if len(entries)>1:
            raise SaxoTradingSafetyError("Saxo exact OrderId returned multiple latest order states")
        if not entries:
            return {"available":False,"reason":"NO_ORDER_ACTIVITY"}
        row=entries[0]
        if not isinstance(row,Mapping) or str(row.get("OrderId") or '')!=order:
            raise SaxoTradingSafetyError("Saxo historical order identity mismatch")
        reported_account=str(row.get("AccountId") or "").strip()
        if not reported_account or reported_account!=identity:
            raise SaxoTradingSafetyError("Saxo historical order account identity unverified")
        if row.get("Uic") is not None and int(row["Uic"])!=int(uic):
            raise SaxoTradingSafetyError("Saxo historical order UIC mismatch")
        if row.get("AssetType") is not None and str(row["AssetType"])!=str(asset_type):
            raise SaxoTradingSafetyError("Saxo historical order asset type mismatch")
        return {
            "available":True,
            "status":str(row.get("Status") or "").strip() or "UNKNOWN",
            "sub_status":str(row.get("SubStatus") or "").strip(),
            "filled_amount":row.get("FilledAmount"),
            "amount":row.get("Amount"),
            "side":str(row.get("BuySell") or "").strip(),
            "activity_time":str(row.get("ActivityTime") or "").strip(),
            "order_id_suffix":order[-8:],
        }

    def market_status_exact(self, *,account_id:str,uic:int,asset_type:str)->SaxoMarketStatusV3:
        """Read Saxo's account-scoped market state without relying on local schedules."""
        account_key,_=self._account_context_exact(account_id)
        payload=self.client._get("trade/v1/infoprices",params={
            "AccountKey":account_key,
            "Uic":int(uic),
            "AssetType":asset_type,
            "FieldGroups":"InstrumentPriceDetails,Quote",
        })
        details=payload.get("InstrumentPriceDetails") if isinstance(payload.get("InstrumentPriceDetails"),Mapping) else {}
        quote=payload.get("Quote") if isinstance(payload.get("Quote"),Mapping) else {}
        raw_open=details.get("IsMarketOpen")
        is_open=raw_open if isinstance(raw_open,bool) else None
        market_state=str(quote.get("MarketState") or "").strip() or None
        raw_error=str(quote.get("ErrorCode") or "").strip()
        quote_error=None if raw_error.lower() in {"","none","null"} else raw_error
        return SaxoMarketStatusV3(is_open=is_open,market_state=market_state,quote_error=quote_error)

    def net_positions_exact(self, *,account_id:str,uic:int,asset_type:str):
        # /netpositions/me is client-wide and can aggregate the same instrument
        # across accounts. Ask Saxo to scope the calculation to AccountKey instead.
        account_key,client_key=self._account_context_exact(account_id)
        params={"$top":1000,"AccountKey":account_key,"AssetType":asset_type,"Uic":int(uic)}
        if client_key:
            params["ClientKey"]=client_key
        payload=self.client._get("port/v1/netpositions",params=params)
        rows=payload.get("Data") or []
        if not isinstance(rows,list):
            raise SaxoTradingSafetyError("v3 LIVE exact position response is invalid")
        matches=[]
        for row in rows:
            if not isinstance(row,dict):
                continue
            base=row.get("NetPositionBase") if isinstance(row.get("NetPositionBase"),dict) else {}
            if int(base.get("Uic") or -1)!=int(uic) or str(base.get("AssetType") or "")!=str(asset_type):
                continue
            # AccountKey in the request is the authority boundary. If Saxo also
            # returns an account id, require it to agree with the enrollment.
            returned_id=str(base.get("PositionsAccount") or base.get("AccountId") or "").strip()
            if returned_id and returned_id!=str(account_id):
                raise SaxoTradingSafetyError("v3 LIVE account-scoped position identity mismatch")
            matches.append(row)
        if len(matches)>1:
            raise SaxoTradingSafetyError("ambiguous v3 LIVE exact-boundary position state")
        return tuple(matches)
    def open_pnl_exact(self, *,account_id:str,uic:int,asset_type:str)->float:
        """Current P/L for the exact V3 account/product using Saxo's rich view."""
        exact=self.net_positions_exact(account_id=account_id,uic=uic,asset_type=asset_type)
        if not exact:
            return 0.0
        payload=self.client._get("port/v1/netpositions/me",params={"$top":1000})
        rows=payload.get("Data") or []
        matches=[]
        for row in rows:
            if not isinstance(row,dict):
                continue
            base=row.get("NetPositionBase") if isinstance(row.get("NetPositionBase"),dict) else {}
            if str(base.get("PositionsAccount") or base.get("AccountId") or "").strip()!=str(account_id):
                continue
            if int(base.get("Uic") or -1)!=int(uic) or str(base.get("AssetType") or "")!=str(asset_type):
                continue
            matches.append(row)
        if len(matches)!=1:
            raise SaxoTradingSafetyError("v3 LIVE P/L view is missing or ambiguous for exact account/product")
        from autotrader_v3_reset_on_loss_v1 import open_pnl_from_net_position_v3
        return open_pnl_from_net_position_v3(matches[0])
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
