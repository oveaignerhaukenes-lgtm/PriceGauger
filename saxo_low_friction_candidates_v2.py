from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import quote

from saxo_market_inventory_v2 import SaxoMarketInventoryResultV2, precise_market_rows_v2
from saxo_provider import SaxoClient, SaxoInstrument


# These are discovery/inspection families only. Inclusion here does not grant
# AutoTrader execution authority. They are useful because Saxo commonly prices
# them primarily through spread rather than a fixed per-ticket commission.
LOW_FRICTION_MARGIN_ASSET_TYPES: tuple[str, ...] = (
    "FxSpot",
    "CfdOnFutures",
    "CfdOnIndex",
)


@dataclass(frozen=True, slots=True)
class LowFrictionAccountV2:
    account_key: str
    account_id: str
    currency: str

    @property
    def label(self) -> str:
        suffix = self.account_id[-4:] if self.account_id else "????"
        return f"…{suffix} {self.currency}".strip()


@dataclass(frozen=True, slots=True)
class LowFrictionCandidateV2:
    market: str
    uic: int
    asset_type: str
    description: str
    symbol: str
    exchange: str | None
    currency: str | None
    matched_queries: tuple[str, ...]
    bid: float | None
    ask: float | None
    spread_pct: float | None
    minimum_trade_size: float | None
    minimum_order_value: float | None
    increment_size: float | None
    margin_requirement_pct: float | None
    long_commission: float | None
    short_commission: float | None
    commission_currency: str | None
    long_total_cost_pct: float | None
    short_total_cost_pct: float | None
    zero_commission_both_sides: bool | None
    cost_error: str | None
    details_error: str | None
    provisional_margin_candidate: bool
    live_execution_eligible: bool = False


@dataclass(frozen=True, slots=True)
class LowFrictionScanResultV2:
    market: str
    rows: tuple[LowFrictionCandidateV2, ...]
    precise_rows_seen: int
    candidate_rows_seen: int
    inspected: int
    failed: int
    account_labels: tuple[str, ...]


def _number(value: Any, *, allow_zero: bool = False) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if allow_zero:
        return number if number >= 0 else None
    return number if number > 0 else None


def _accounts(client: SaxoClient) -> tuple[LowFrictionAccountV2, ...]:
    payload = client._get("port/v1/accounts/me")
    raw = payload.get("Data") or []
    if not isinstance(raw, list):
        return ()
    result: list[LowFrictionAccountV2] = []
    for item in raw:
        if not isinstance(item, dict) or not item.get("AccountKey"):
            continue
        if item.get("Active") is False:
            continue
        result.append(
            LowFrictionAccountV2(
                account_key=str(item["AccountKey"]),
                account_id=str(item.get("AccountId") or ""),
                currency=str(item.get("Currency") or ""),
            )
        )
    return tuple(result[:3])


def _instrument(market: str, row: Any) -> SaxoInstrument:
    return SaxoInstrument(
        asset=market,
        uic=int(row.identifier),
        asset_type=str(row.asset_type),
        symbol=str(row.symbol or ""),
        description=str(row.description or ""),
    )


def _quote_fields(payload: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
    quote_data = payload.get("Quote") if isinstance(payload.get("Quote"), dict) else {}
    bid = _number(quote_data.get("Bid"))
    ask = _number(quote_data.get("Ask"))
    mid = _number(quote_data.get("Mid"))
    if mid is None and bid is not None and ask is not None:
        mid = (bid + ask) / 2.0
    spread_pct = None
    if bid is not None and ask is not None and mid is not None and mid > 0:
        spread_pct = (ask - bid) / mid
    return bid, ask, spread_pct


def _details_fields(payload: dict[str, Any]) -> tuple[float | None, float | None, float | None, float | None]:
    minimum_trade_size = _number(payload.get("MinimumTradeSize") or payload.get("MinimumLotSize"))
    minimum_order_value = _number(payload.get("MinimumOrderValue"))
    increment_size = _number(payload.get("IncrementSize"))

    # Saxo's schemas vary by AssetType/account. Keep this tolerant and purely
    # observational: if a margin percentage is not exposed, leave it unknown.
    margin_requirement_pct = None
    for key in (
        "InitialMarginPercent",
        "InitialMarginRequirement",
        "MarginRequirement",
        "MarginPercent",
    ):
        value = _number(payload.get(key), allow_zero=True)
        if value is not None:
            margin_requirement_pct = value
            break
    return minimum_trade_size, minimum_order_value, increment_size, margin_requirement_pct


def _sum_commissions(trading_cost: dict[str, Any]) -> float | None:
    commissions = trading_cost.get("Commissions")
    if commissions is None:
        return 0.0
    if not isinstance(commissions, list):
        return None
    total = 0.0
    seen = False
    for item in commissions:
        if not isinstance(item, dict):
            continue
        value = _number(item.get("Value"), allow_zero=True)
        if value is None:
            continue
        total += value
        seen = True
    return total if seen or not commissions else None


def _cost_side(payload: dict[str, Any], side_name: str) -> tuple[float | None, float | None, str | None]:
    cost = payload.get("Cost") if isinstance(payload.get("Cost"), dict) else {}
    side = cost.get(side_name) if isinstance(cost.get(side_name), dict) else {}
    trading_cost = side.get("TradingCost") if isinstance(side.get("TradingCost"), dict) else {}
    commission = _sum_commissions(trading_cost)
    total_cost_pct = _number(side.get("TotalCostPct"), allow_zero=True)
    currency = str(side.get("Currency") or payload.get("AccountCurrency") or "") or None
    return commission, total_cost_pct, currency


def _cost_illustration(
    client: SaxoClient,
    *,
    account: LowFrictionAccountV2 | None,
    instrument: SaxoInstrument,
    amount: float,
    price: float,
) -> tuple[
    float | None,
    float | None,
    str | None,
    float | None,
    float | None,
    bool | None,
    str | None,
]:
    if account is None:
        return None, None, None, None, None, None, "AccountKey unavailable"
    path = (
        f"cs/v1/tradingconditions/cost/{quote(account.account_key, safe='')}/"
        f"{instrument.uic}/{instrument.asset_type}"
    )
    try:
        payload = client._get(
            path,
            params={
                "Amount": amount,
                "ApplyCostsZeroFloor": False,
                "HoldingPeriodInDays": 1,
                "Price": price,
                "TradeContext": "ClientTrading",
            },
        )
    except Exception as exc:
        return None, None, None, None, None, None, f"{type(exc).__name__}: {exc}"

    long_commission, long_total, long_currency = _cost_side(payload, "Long")
    short_commission, short_total, short_currency = _cost_side(payload, "Short")
    currency = long_currency or short_currency
    if long_commission is None or short_commission is None:
        zero_both = None
    else:
        zero_both = abs(long_commission) <= 1e-12 and abs(short_commission) <= 1e-12
    return (
        long_commission,
        short_commission,
        currency,
        long_total,
        short_total,
        zero_both,
        None,
    )


def scan_low_friction_margin_candidates_v2(
    client: SaxoClient,
    *,
    inventory: SaxoMarketInventoryResultV2,
    max_products: int = 20,
) -> LowFrictionScanResultV2:
    """Inspect precise market-linked FX/CFD rows for low transaction friction.

    This scanner intentionally accepts margin products as research candidates. It
    does NOT add them to the PriceGauger execution universe and never grants LIVE
    entry authority. Negative-balance protection is therefore a design assumption
    pending explicit account verification, not an execution guarantee.
    """

    precise_rows = precise_market_rows_v2(inventory)
    candidate_rows = tuple(
        row for row in precise_rows if row.asset_type in LOW_FRICTION_MARGIN_ASSET_TYPES
    )
    candidates = candidate_rows[: max(1, int(max_products))]
    accounts = _accounts(client)
    account = accounts[0] if accounts else None

    result: list[LowFrictionCandidateV2] = []
    failed = 0
    for row in candidates:
        instrument = _instrument(inventory.market, row)
        bid = ask = spread_pct = None
        minimum_trade_size = minimum_order_value = increment_size = margin_requirement_pct = None
        details_error = cost_error = None
        long_commission = short_commission = None
        long_total_cost_pct = short_total_cost_pct = None
        commission_currency = None
        zero_commission_both_sides = None

        try:
            info = client.info_price(instrument)
            bid, ask, spread_pct = _quote_fields(info)
        except Exception as exc:
            details_error = f"price: {type(exc).__name__}: {exc}"

        try:
            details = client.instrument_details(instrument)
            (
                minimum_trade_size,
                minimum_order_value,
                increment_size,
                margin_requirement_pct,
            ) = _details_fields(details)
        except Exception as exc:
            message = f"details: {type(exc).__name__}: {exc}"
            details_error = f"{details_error}; {message}" if details_error else message

        price = ask or bid
        amount = minimum_trade_size or increment_size or 1.0
        if price is not None and price > 0 and amount > 0:
            (
                long_commission,
                short_commission,
                commission_currency,
                long_total_cost_pct,
                short_total_cost_pct,
                zero_commission_both_sides,
                cost_error,
            ) = _cost_illustration(
                client,
                account=account,
                instrument=instrument,
                amount=amount,
                price=price,
            )
        else:
            cost_error = "Price or minimum amount unavailable for cost illustration"

        if details_error and cost_error:
            failed += 1

        result.append(
            LowFrictionCandidateV2(
                market=inventory.market,
                uic=instrument.uic,
                asset_type=instrument.asset_type,
                description=instrument.description or instrument.symbol or f"UIC {instrument.uic}",
                symbol=instrument.symbol,
                exchange=row.exchange_name or row.exchange_id,
                currency=row.currency,
                matched_queries=row.matched_queries,
                bid=bid,
                ask=ask,
                spread_pct=spread_pct,
                minimum_trade_size=minimum_trade_size,
                minimum_order_value=minimum_order_value,
                increment_size=increment_size,
                margin_requirement_pct=margin_requirement_pct,
                long_commission=long_commission,
                short_commission=short_commission,
                commission_currency=commission_currency,
                long_total_cost_pct=long_total_cost_pct,
                short_total_cost_pct=short_total_cost_pct,
                zero_commission_both_sides=zero_commission_both_sides,
                cost_error=cost_error,
                details_error=details_error,
                provisional_margin_candidate=True,
                live_execution_eligible=False,
            )
        )

    result.sort(
        key=lambda item: (
            0 if item.zero_commission_both_sides is True else 1,
            float("inf") if item.spread_pct is None else item.spread_pct,
            float("inf")
            if item.long_total_cost_pct is None and item.short_total_cost_pct is None
            else max(item.long_total_cost_pct or 0.0, item.short_total_cost_pct or 0.0),
            item.description.lower(),
            item.uic,
        )
    )
    return LowFrictionScanResultV2(
        market=inventory.market,
        rows=tuple(result),
        precise_rows_seen=len(precise_rows),
        candidate_rows_seen=len(candidate_rows),
        inspected=len(candidates),
        failed=failed,
        account_labels=tuple(item.label for item in accounts),
    )


def low_friction_rows_for_ui_v2(rows: Iterable[LowFrictionCandidateV2]) -> list[dict[str, object]]:
    return [
        {
            "Produkt": item.description,
            "Symbol": item.symbol,
            "AssetType": item.asset_type,
            "Børs": item.exchange or "",
            "Valuta": item.currency or "",
            "Bid": item.bid,
            "Ask": item.ask,
            "Spread %": None if item.spread_pct is None else item.spread_pct * 100.0,
            "Min. størrelse": item.minimum_trade_size,
            "Min. ordreverdi": item.minimum_order_value,
            "Steg": item.increment_size,
            "Margin % (API)": item.margin_requirement_pct,
            "Kurtasje LONG*": item.long_commission,
            "Kurtasje SHORT*": item.short_commission,
            "Kurtasjevaluta": item.commission_currency or "",
            "0 kurtasje begge": item.zero_commission_both_sides,
            "Total kost LONG %*": item.long_total_cost_pct,
            "Total kost SHORT %*": item.short_total_cost_pct,
            "Treff via": ", ".join(item.matched_queries),
            "LIVE eligible": item.live_execution_eligible,
            "Kost-feil": item.cost_error or "",
            "Detalj-feil": item.details_error or "",
            "UIC": item.uic,
        }
        for item in rows
    ]
