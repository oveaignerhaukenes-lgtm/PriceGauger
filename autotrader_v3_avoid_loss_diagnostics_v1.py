"""Operator-only Saxo GET diagnostics for Avoid Loss V1.

This is a diagnostic, never an arming precondition or execution authority.
No order/precheck/POST, writes, raw broker payloads, identifying values,
prices, P/L, account keys or position quantities are returned.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Mapping

from autotrader_v3_avoid_loss_readiness_v1 import _signed_amount, _number


@dataclass(frozen=True, slots=True)
class SaxoEvidenceDiagnosticV1:
    status: str
    phase: str
    code: str
    observed: tuple[str, ...]
    live_ready: bool = False

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


def _result(status: str, phase: str, code: str, seen: list[str]) -> SaxoEvidenceDiagnosticV1:
    return SaxoEvidenceDiagnosticV1(status, phase, code, tuple(seen))


def _quote_issue(view: Mapping, now: datetime) -> str | None:
    if str(view.get("CalculationReliability") or "").lower() != "ok":
        return "QUOTE_RELIABILITY_UNVERIFIED"
    try:
        delay = _number(view.get("CurrentPriceDelayMinutes"))
    except (ValueError, TypeError, OverflowError):
        return "QUOTE_DELAY_MISSING_OR_INVALID"
    if delay != 0:
        return "QUOTE_DELAYED"
    marker = view.get("CurrentPriceLastTraded")
    if marker is None or marker == "":
        return "LAST_TRADED_TIMESTAMP_MISSING"
    if not isinstance(marker, str):
        return "LAST_TRADED_MARKER_NOT_TIMESTAMP"
    try:
        timestamp = datetime.fromisoformat(marker.replace("Z", "+00:00"))
    except (ValueError, TypeError, OverflowError):
        return "LAST_TRADED_MARKER_NOT_TIMESTAMP"
    if timestamp.tzinfo is None:
        return "LAST_TRADED_TIMESTAMP_NO_TIMEZONE"
    elapsed = (now - timestamp.astimezone(timezone.utc)).total_seconds()
    if not isfinite(elapsed) or elapsed < 0:
        return "LAST_TRADED_TIMESTAMP_FUTURE"
    if elapsed > 10:
        return "LAST_TRADED_TIMESTAMP_STALE"
    return None


def diagnose_saxo_avoid_loss_v1(
    *, broker: Any, account_id: str, uic: int, asset_type: str,
    now: datetime | None = None,
) -> SaxoEvidenceDiagnosticV1:
    """Diagnose only one operator-selected account and instrument, GET-only.

    A fresh last-traded marker alone does NOT verify executable quote
    freshness. For that reason even the best outcome remains NOT_LIVE_READY.
    """
    seen: list[str] = []
    if broker is None:
        return _result("BLOCKED","CLIENT","SAXO_READ_CLIENT_MISSING",seen)
    try:
        identity = str(account_id or "").strip()
        asset = str(asset_type or "").strip()
        instrument = int(uic)
        clock = now or datetime.now(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return _result("BLOCKED","INPUT","INVALID_ACCOUNT_INSTRUMENT_OR_CLOCK",seen)
    if not identity or not asset or instrument <= 0 or clock.tzinfo is None:
        return _result("BLOCKED","INPUT","INVALID_ACCOUNT_INSTRUMENT_OR_CLOCK",seen)
    clock = clock.astimezone(timezone.utc)
    try:
        accounts = broker.accounts()
    except Exception:
        return _result("BLOCKED","ACCOUNT_GET","SAXO_ACCOUNT_GET_FAILED",seen)
    if not isinstance(accounts,(tuple,list)):
        return _result("BLOCKED","ACCOUNT_GET","SAXO_ACCOUNTS_INVALID",seen)
    matching = [a for a in accounts if isinstance(a, Mapping)
                and str(a.get("AccountId") or "").strip() == identity]
    if len(matching) != 1:
        return _result("BLOCKED","ACCOUNT","ACCOUNT_ID_NOT_UNIQUE",seen)
    if str(matching[0].get("Currency") or "").upper() != "NOK":
        return _result("BLOCKED","ACCOUNT","ACCOUNT_NOT_VERIFIED_NOK",seen)
    seen.append("EXACT_NOK_ACCOUNT")
    kw={"account_id":identity,"uic":instrument,"asset_type":asset}
    try:
        net = broker.net_positions_exact(**kw)
    except Exception:
        return _result("BLOCKED","NET_GET","SAXO_NET_GET_FAILED",seen)
    if not isinstance(net,(tuple,list)):
        return _result("BLOCKED","NET_GET","SAXO_NET_INVALID",seen)
    seen.append("NET_READ_OK")
    try:
        individual = broker.positions_exact(**kw)
    except Exception:
        return _result("BLOCKED","POSITION_GET","SAXO_POSITION_GET_FAILED",seen)
    if not isinstance(individual,(tuple,list)):
        return _result("BLOCKED","POSITION_GET","SAXO_POSITION_INVALID",seen)
    seen.append("INDIVIDUAL_READ_OK")
    if len(net)>1 or len(individual)>1:
        return _result("BLOCKED","POSITION_COUNT","MULTIPLE_POSITIONS_NOT_SUPPORTED",seen)
    if not net and not individual:
        return _result("FLAT_OBSERVED","POSITION_COUNT","NO_OPEN_POSITION_FOR_PNL_VALIDATION",seen)
    if len(net)!=1 or len(individual)!=1:
        return _result("BLOCKED","POSITION_COUNT","NET_INDIVIDUAL_DISAGREE",seen)
    netrow, posrow = net[0], individual[0]
    if not isinstance(netrow,Mapping) or not isinstance(posrow,Mapping):
        return _result("BLOCKED","POSITION_SHAPE","POSITION_ROW_INVALID",seen)
    netbase, base, view = netrow.get("NetPositionBase"),posrow.get("PositionBase"),posrow.get("PositionView")
    if not isinstance(netbase,Mapping) or not isinstance(base,Mapping):
        return _result("BLOCKED","POSITION_SHAPE","POSITION_BASE_MISSING",seen)
    if not isinstance(view,Mapping):
        return _result("BLOCKED","POSITION_SHAPE","POSITION_VIEW_MISSING",seen)
    if str(base.get("AccountId") or base.get("PositionsAccount") or "").strip() != identity:
        return _result("BLOCKED","POSITION_IDENTITY","POSITION_ACCOUNT_MISMATCH",seen)
    reported_net_id=str(netbase.get("PositionsAccount") or netbase.get("AccountId") or "").strip()
    if reported_net_id and reported_net_id!=identity:
        return _result("BLOCKED","POSITION_IDENTITY","NET_ACCOUNT_MISMATCH",seen)
    try:
        matches=all(int(x.get("Uic") or -1)==instrument
                    and str(x.get("AssetType") or "")==asset for x in (netbase,base))
    except (ValueError,TypeError,OverflowError):
        matches=False
    if not matches:
        return _result("BLOCKED","POSITION_IDENTITY","INSTRUMENT_MISMATCH",seen)
    if not str(posrow.get("PositionId") or "").strip():
        return _result("BLOCKED","POSITION_IDENTITY","INDIVIDUAL_POSITION_ID_MISSING",seen)
    seen.append("POSITION_IDENTITIES_MATCH")
    if str(base.get("Status") or "").lower() not in {"open","partiallyclosed"}:
        return _result("BLOCKED","POSITION_STATE","POSITION_STATUS_UNVERIFIED",seen)
    if base.get("CanBeClosed") is False:
        return _result("BLOCKED","POSITION_STATE","POSITION_CANNOT_CLOSE",seen)
    try:
        signed=_signed_amount(dict(netbase))
    except (ValueError, TypeError, OverflowError):
        return _result("BLOCKED","NET_DIRECTION","NET_DIRECTION_OR_AMOUNT_INVALID",seen)
    try:
        amount=abs(_number(base.get("Amount")))
    except (ValueError,TypeError,OverflowError):
        return _result("BLOCKED","POSITION_AMOUNT","INDIVIDUAL_AMOUNT_INVALID",seen)
    if amount<=0 or abs(signed)<=0 or abs(abs(signed)-amount)>1e-9:
        return _result("BLOCKED","INVENTORY_MATCH","POSITION_QUANTITY_NOT_MATCHING",seen)
    seen.append("SIGNED_INVENTORY_MATCH")
    try:
        _number(view.get("ProfitLossOnTradeInBaseCurrency"))
    except (ValueError,TypeError,OverflowError):
        return _result("BLOCKED","PNL","TRADE_PNL_BASE_CURRENCY_INVALID",seen)
    seen.append("PNL_BASE_FIELD_NUMERIC")
    try:
        costs=_number(view.get("TradeCostsTotalInBaseCurrency"))
    except (ValueError,TypeError,OverflowError):
        return _result("BLOCKED","COSTS","TRADE_COST_BASE_CURRENCY_INVALID",seen)
    if costs<0:
        return _result("BLOCKED","COSTS","TRADE_COST_NEGATIVE",seen)
    seen.append("COST_BASE_FIELD_NUMERIC")
    issue=_quote_issue(view,clock)
    if issue:
        return _result("BLOCKED","QUOTE",issue,seen)
    seen.append("LAST_TRADED_MARKER_RECENT")
    return _result(
        "FIELDS_OBSERVED_NOT_LIVE_READY","MARGIN_COST_EXECUTION_GATE",
        "FROZEN_ENTRY_MARGIN_FINANCING_AND_CLOSE_TO_FLAT_UNPROVEN",seen
    )


__all__=["SaxoEvidenceDiagnosticV1","diagnose_saxo_avoid_loss_v1"]
