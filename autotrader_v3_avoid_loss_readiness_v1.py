"""Operator-invoked, read-only Saxo evidence probe for Avoid Loss V1.

This is deliberately NOT a strategy, order guard, emergency stop or arming
gate. It never invokes precheck, place_order, any POST or a database write.
It reports only non-sensitive field-presence and quality verdicts; no IDs,
account values, prices, profit/loss, position quantities or auth tokens.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Any

MAX_QUOTE_AGE_SECONDS = 10


@dataclass(frozen=True, slots=True)
class SaxoReadinessProbeV1:
    status: str
    observed: tuple[str, ...]
    blockers: tuple[str, ...]
    live_ready: bool = False

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


def _stop(reason: str, observed: tuple[str, ...] = ()) -> SaxoReadinessProbeV1:
    return SaxoReadinessProbeV1("BLOCKED", observed, (reason,))


def _number(raw: Any) -> float:
    if raw is None or isinstance(raw, bool):
        raise ValueError("non-numeric")
    value = float(raw)
    if not isfinite(value):
        raise ValueError("nonfinite")
    return value


def _signed_amount(base: dict) -> float:
    if base.get("AmountLong") is not None or base.get("AmountShort") is not None:
        long_amt = _number(base.get("AmountLong") if base.get("AmountLong") is not None else 0)
        short_amt = _number(base.get("AmountShort") if base.get("AmountShort") is not None else 0)
        if long_amt < 0 or short_amt < 0 or (long_amt > 0 and short_amt > 0):
            raise ValueError("gross or hedged")
        return long_amt - short_amt
    amt = _number(base.get("Amount"))
    direction = str(base.get("OpeningDirection") or "").lower()
    if amt == 0:
        return 0.0
    if direction not in {"buy", "sell"}:
        raise ValueError("net direction unproven")
    return abs(amt) if direction == "buy" else -abs(amt)


def _quote_is_fresh(view: dict, now: datetime) -> bool:
    if str(view.get("CalculationReliability") or "").lower() != "ok":
        return False
    delay = view.get("CurrentPriceDelayMinutes")
    if isinstance(delay, bool) or delay is None or _number(delay) != 0:
        return False
    quoted = view.get("CurrentPriceLastTraded")
    if not isinstance(quoted, str) or not quoted.strip():
        return False
    moment = datetime.fromisoformat(quoted.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        return False
    age = (now - moment.astimezone(timezone.utc)).total_seconds()
    return 0 <= age <= MAX_QUOTE_AGE_SECONDS


def inspect_saxo_avoid_loss_readonly_v1(
    *, broker: Any, account_id: str, uic: int, asset_type: str,
    now: datetime | None = None,
) -> SaxoReadinessProbeV1:
    """Read exact accounts/net positions/individual positions, never mutate.

    OPEN existing positions may supply evidence about real PositionView fields,
    but they are NEVER adopted as new Avoid Loss trades: original order margin,
    order audit, real net NAV, and CLOSE->FLAT are still unproven.
    """
    if broker is None:
        return _stop("SAXO_READ_CLIENT_MISSING")
    if not str(account_id).strip() or not str(asset_type).strip() or int(uic) <= 0:
        return _stop("EXACT_ACCOUNT_PRODUCT_REQUIRED")
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        return _stop("UTC_CLOCK_REQUIRED")
    clock = clock.astimezone(timezone.utc)
    seen: list[str] = []
    try:
        accounts = broker.accounts()
        matching = [x for x in accounts if isinstance(x, dict) and
                    str(x.get("AccountId") or "") == str(account_id)]
        if len(matching) != 1:
            return _stop("ACCOUNT_IDENTITY_NOT_UNIQUE")
        if str(matching[0].get("Currency") or "").upper() != "NOK":
            return _stop("ACCOUNT_CURRENCY_NOT_NOK")
        seen.append("EXACT_NOK_ACCOUNT")
        net = broker.net_positions_exact(account_id=account_id, uic=int(uic),
                                          asset_type=asset_type)
        positions = broker.positions_exact(account_id=account_id, uic=int(uic),
                                            asset_type=asset_type)
        if len(net) > 1 or len(positions) > 1:
            return _stop("AMBIGUOUS_POSITION_COUNT", tuple(seen))
        if not net and not positions:
            return SaxoReadinessProbeV1(
                "FLAT_OBSERVED", tuple(seen)+("ACCOUNT_PRODUCT_FLAT",),
                ("NO_OPEN_POSITION_FOR_PNL_VERIFICATION",
                 "NO_CONFIRMED_ENTRY_MARGIN",
                 "NO_CONFIRMED_CLOSE_TO_FLAT"))
        if len(net) != 1 or len(positions) != 1:
            return _stop("NET_INDIVIDUAL_INCONSISTENT", tuple(seen))
        netbase, posbase = net[0].get("NetPositionBase"), positions[0].get("PositionBase")
        view = positions[0].get("PositionView")
        if not all(isinstance(x, dict) for x in (netbase, posbase, view)):
            return _stop("POSITION_FIELDS_UNAVAILABLE", tuple(seen))
        net_id = str(netbase.get("PositionsAccount") or netbase.get("AccountId") or "")
        pos_id = str(posbase.get("AccountId") or posbase.get("PositionsAccount") or "")
        if (net_id and net_id != str(account_id)) or pos_id != str(account_id):
            return _stop("RETURNED_ACCOUNT_MISMATCH", tuple(seen))
        for base in (netbase, posbase):
            if int(base.get("Uic") or -1) != int(uic) or str(base.get("AssetType") or "") != asset_type:
                return _stop("RETURNED_INSTRUMENT_MISMATCH", tuple(seen))
        signed = _signed_amount(netbase)
        size = abs(_number(posbase.get("Amount")))
        if signed == 0 or size == 0 or abs(abs(signed)-size) > 1e-9:
            return _stop("SIGNED_INVENTORY_NOT_ONE_POSITION", tuple(seen))
        if not str(positions[0].get("PositionId") or "").strip():
            return _stop("POSITION_ID_MISSING", tuple(seen))
        if str(posbase.get("Status") or "").lower() not in {"open", "partiallyclosed"}:
            return _stop("POSITION_NOT_OPEN", tuple(seen))
        if posbase.get("CanBeClosed") is False:
            return _stop("POSITION_CANNOT_CLOSE", tuple(seen))
        seen.append("NET_AND_INDIVIDUAL_POSITION_MATCH")
        if not _quote_is_fresh(view, clock):
            return _stop("FRESH_RELIABLE_QUOTE_UNVERIFIED", tuple(seen))
        seen.append("QUOTED_AT_WITHIN_10_SECONDS")
        _number(view.get("ProfitLossOnTradeInBaseCurrency"))
        if _number(view.get("TradeCostsTotalInBaseCurrency")) < 0:
            return _stop("NEGATIVE_COSTS", tuple(seen))
        seen.append("POSITION_PNL_AND_COST_FIELDS_PRESENT")
        return SaxoReadinessProbeV1(
            "POSITION_FIELDS_OBSERVED", tuple(seen),
            ("NO_CONFIRMED_ENTRY_MARGIN",
             "NO_COST_AND_FINANCING_RECONCILIATION",
             "NO_ORDER_AUDIT_FINAL_FILL",
             "NO_CONFIRMED_CLOSE_TO_FLAT"))
    except (ValueError, TypeError, KeyError, OverflowError):
        return _stop("SAXO_RESPONSE_VALIDATION_FAILED", tuple(seen))
    except Exception:
        # Do not leak broker errors: these may include account or request details.
        return _stop("SAXO_READ_FAILED", tuple(seen))


__all__ = ["SaxoReadinessProbeV1", "inspect_saxo_avoid_loss_readonly_v1"]
