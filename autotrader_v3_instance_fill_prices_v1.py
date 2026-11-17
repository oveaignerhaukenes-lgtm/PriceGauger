"""Read-only Saxo FinalFill prices for one V3 instance's inspection chart.

V3's durable execution ledger proves broker inventory reconciliation but does
not record the actual deal price.  Never present a candle high/low as a fill.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Mapping, Sequence

from autotrader_v3_live_saxo_v1 import configured_live_pilot_client_v3
from trading_desk import utc


def _positive(value):
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    return number if isfinite(number) and number > 0 else None


def match_exact_final_fills_v1(
    executions: Sequence[Mapping], activities: Sequence[Mapping], *,
    account_id: str, uic: int, asset_type: str,
) -> dict[str, dict]:
    """Match exact account/product/order/side/amount; reject ambiguous fills.

    Multiple genuinely partial FinalFill activities are weighted only when
    their filled amounts add up to V3 quantity and each reports an individual
    trade Price. Cumulative AveragePrice is not safe to re-average.
    """
    expected = {
        str(event.get("broker_order_id") or "").strip(): event
        for event in executions if str(event.get("broker_order_id") or "").strip()
    }
    grouped = defaultdict(list)
    seen_logs = set()
    for row in activities:
        if not isinstance(row, Mapping):
            continue
        order_id = str(row.get("OrderId") or "").strip()
        event = expected.get(order_id)
        if event is None:
            continue
        if str(row.get("Status") or "") != "FinalFill":
            continue
        if str(row.get("SubStatus") or "") not in {"", "Confirmed"}:
            continue
        if str(row.get("AccountId") or "") != str(account_id):
            continue
        if str(row.get("AssetType") or "") != str(asset_type):
            continue
        try:
            if int(row.get("Uic")) != int(uic):
                continue
        except (ValueError, TypeError):
            continue
        if str(row.get("BuySell") or "").upper() != str(event.get("side") or "").upper():
            continue
        price = _positive(row.get("AveragePrice")) or _positive(row.get("Price"))
        amount = (_positive(row.get("FilledAmount")) or _positive(row.get("FillAmount"))
                  or _positive(row.get("Amount")))
        if price is None or amount is None:
            continue
        try:
            fill_at = utc(row["ActivityTime"])
        except (ValueError, TypeError, KeyError):
            continue
        log_id = str(row.get("LogId") or "").strip()
        if log_id and (order_id, log_id) in seen_logs:
            continue
        if log_id:
            seen_logs.add((order_id, log_id))
        grouped[order_id].append((amount, price, fill_at, _positive(row.get("Price"))))

    verified = {}
    for order_id, fills in grouped.items():
        event_amount = _positive(expected[order_id].get("amount"))
        total = sum(amount for amount, _, _, _ in fills)
        if event_amount is None or abs(total-event_amount) > 1e-7:
            continue
        if len(fills) > 1:
            if any(individual_price is None for _,_,_,individual_price in fills):
                continue
            weighted_price = sum(amount*individual_price for amount,_,_,individual_price in fills)/total
        else:
            weighted_price = fills[0][1]
        verified[order_id] = {
            "execution_price": weighted_price,
            "filled_at": max(at for _,_,at,_ in fills),
            "price_source": "SAXO_FINAL_FILL",
        }
    return verified


def fetch_exact_final_fills_v1(
    executions: Sequence[Mapping], *, account_id: str, uic: int,
    asset_type: str, now: datetime | None = None, broker=None,
) -> dict[str, dict]:
    """One account-scoped Saxo READ; no order mutation or inferred fill price.

    A paginated response is incomplete: fail closed rather than guessing which
    order activities were omitted. Caller may present approximate markers.
    """
    pending = tuple(event for event in executions
                    if str(event.get("broker_order_id") or "").strip())
    if not pending:
        return {}
    client = broker if broker is not None else configured_live_pilot_client_v3()
    if client is None:
        return {}
    account_key, client_key = client._account_context_exact(str(account_id))
    start = min(utc(event["executed_at"]) for event in pending)-timedelta(hours=1)
    end = utc(now or datetime.now(timezone.utc))
    params = {
        "AccountKey": account_key,
        "EntryType": "All",
        "FromDateTime": start.isoformat().replace("+00:00", "Z"),
        "ToDateTime": end.isoformat().replace("+00:00", "Z"),
        "$top": 500,
    }
    if client_key:
        params["ClientKey"] = client_key
    payload = client.client._get("cs/v1/audit/orderactivities", params=params)
    if not isinstance(payload, Mapping) or payload.get("__next"):
        raise ValueError("Saxo order audit is incomplete or paginated")
    activities = payload.get("Data")
    if not isinstance(activities, list):
        raise ValueError("Saxo order audit Data is missing")
    if len(activities) >= 500:
        raise ValueError("Saxo order audit reached the bounded result limit")
    return match_exact_final_fills_v1(
        pending, activities, account_id=account_id, uic=uic, asset_type=asset_type)


def attach_verified_fill_prices_v1(executions: Sequence[Mapping], prices: Mapping[str, Mapping]):
    """Attach provenance without mutating the immutable worker execution rows."""
    return tuple({**event, **prices.get(str(event.get("broker_order_id") or ""), {})}
                 for event in executions)


__all__ = ["match_exact_final_fills_v1", "fetch_exact_final_fills_v1",
           "attach_verified_fill_prices_v1"]
