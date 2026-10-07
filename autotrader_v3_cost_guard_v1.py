from __future__ import annotations

"""Broker-authoritative transaction-friction guard for V3 LIVE.

Saxo's pre-trade cost illustration includes open + close costs. V3 uses that
read-only source before LIVE arming and again in runtime before OPEN/ADD.
Risk-reducing REDUCE/CLOSE actions are never blocked by this module.
"""

from dataclasses import dataclass
import math
from typing import Any
from urllib.parse import quote

from autotrader_open_sizing_v2 import load_entry_instrument_rules_v2, minimum_legal_amount_v2
from saxo_provider import SaxoInstrument

COST_WARN_TOTAL_PCT_V3 = 0.5
COST_BLOCK_TOTAL_PCT_V3 = 2.0


@dataclass(frozen=True, slots=True)
class TransactionCostAssessmentV3:
    severity: str
    amount: float
    long_total_cost_pct: float | None
    short_total_cost_pct: float | None
    long_commission: float | None
    short_commission: float | None
    commission_currency: str | None
    assumptions: tuple[str, ...]
    detail: str

    @property
    def max_total_cost_pct(self) -> float | None:
        values = [
            value
            for value in (self.long_total_cost_pct, self.short_total_cost_pct)
            if value is not None
        ]
        return max(values) if values else None

    @property
    def blocked(self) -> bool:
        return self.severity == "RED"


def _number(value: Any, *, allow_zero: bool = True) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    if allow_zero:
        return parsed if parsed >= 0 else None
    return parsed if parsed > 0 else None


def _sum_commissions(side: dict[str, Any]) -> float | None:
    trading = side.get("TradingCost") if isinstance(side.get("TradingCost"), dict) else {}
    raw = trading.get("Commissions")
    if raw is None:
        return 0.0
    if not isinstance(raw, list):
        return None
    total = 0.0
    seen = False
    for item in raw:
        if not isinstance(item, dict):
            continue
        value = _number(item.get("Value"))
        if value is None:
            continue
        total += value
        seen = True
    return total if seen or not raw else None


def _side(payload: dict[str, Any], key: str) -> tuple[float | None, float | None, str | None]:
    cost = payload.get("Cost") if isinstance(payload.get("Cost"), dict) else {}
    side = cost.get(key) if isinstance(cost.get(key), dict) else {}
    total_pct = _number(side.get("TotalCostPct"))
    commission = _sum_commissions(side)
    currency = str(side.get("Currency") or payload.get("AccountCurrency") or "").strip() or None
    return total_pct, commission, currency


def _exact_account(broker, account_id: str) -> tuple[str, str]:
    matches: list[tuple[str, str]] = []
    for row in broker.accounts():
        if not isinstance(row, dict):
            continue
        if str(row.get("AccountId") or "").strip() != str(account_id):
            continue
        account_key = str(row.get("AccountKey") or "").strip()
        currency = str(row.get("Currency") or "").strip().upper()
        if account_key:
            matches.append((account_key, currency))
    if len(matches) != 1:
        raise ValueError("Saxo account identity is missing or ambiguous for cost guard")
    return matches[0]


def _reference_price(broker, *, account_key: str, instrument: SaxoInstrument) -> float:
    payload = broker.client._get(
        "trade/v1/infoprices",
        params={
            "AccountKey": account_key,
            "Uic": int(instrument.uic),
            "AssetType": instrument.asset_type,
            "FieldGroups": "Quote",
        },
    )
    quote_data = payload.get("Quote") if isinstance(payload.get("Quote"), dict) else {}
    for key in ("Mid", "Ask", "Bid"):
        value = _number(quote_data.get(key), allow_zero=False)
        if value is not None:
            return value
    raise ValueError("Saxo cost guard could not obtain a usable reference price")


def assess_transaction_cost_v3(
    *,
    broker,
    account_id: str,
    market_name: str,
    uic: int,
    asset_type: str,
    amount: float | None = None,
) -> TransactionCostAssessmentV3:
    """Assess Saxo's open+close friction for one exact account/product.

    If amount is omitted, the exact Saxo minimum legal amount is assessed.
    Unknown/unverifiable cost is deliberately RED so LIVE cannot start blind.
    """

    try:
        account_key, _currency = _exact_account(broker, account_id)
        instrument = SaxoInstrument(
            asset=str(market_name),
            uic=int(uic),
            asset_type=str(asset_type),
        )
        if amount is None:
            rules = load_entry_instrument_rules_v2(
                broker.client,
                account_key=account_key,
                instrument=instrument,
            )
            assessed_amount = minimum_legal_amount_v2(rules)
        else:
            assessed_amount = float(amount)
        if assessed_amount <= 0:
            raise ValueError("cost guard amount must be positive")
        price = _reference_price(
            broker,
            account_key=account_key,
            instrument=instrument,
        )
        path = (
            f"cs/v1/tradingconditions/cost/{quote(account_key, safe='')}/"
            f"{int(uic)}/{asset_type}"
        )
        payload = broker.client._get(
            path,
            params={
                "Amount": assessed_amount,
                "ApplyCostsZeroFloor": False,
                "HoldingPeriodInDays": 1,
                "Price": price,
                "TradeContext": "ClientTrading",
            },
        )
        if not isinstance(payload, dict):
            raise ValueError("Saxo cost illustration response is invalid")

        long_pct, long_commission, long_currency = _side(payload, "Long")
        short_pct, short_commission, short_currency = _side(payload, "Short")
        values = [value for value in (long_pct, short_pct) if value is not None]
        if not values:
            raise ValueError("Saxo did not expose TotalCostPct for this instrument")
        worst = max(values)
        assumptions_raw = payload.get("CostCalculationAssumptions") or ()
        assumptions = (
            tuple(str(item) for item in assumptions_raw)
            if isinstance(assumptions_raw, list)
            else ()
        )
        currency = long_currency or short_currency

        if worst >= COST_BLOCK_TOTAL_PCT_V3:
            severity = "RED"
            detail = (
                f"Saxo estimert inn/ut-kostnad er {worst:.2f}% ved amount "
                f"{assessed_amount:g}; LIVE sperret."
            )
        elif worst >= COST_WARN_TOTAL_PCT_V3:
            severity = "YELLOW"
            detail = (
                f"Saxo estimert inn/ut-kostnad er {worst:.2f}% ved amount "
                f"{assessed_amount:g}; høy handelsfriksjon."
            )
        else:
            severity = "GREEN"
            detail = (
                f"Saxo estimert inn/ut-kostnad er {worst:.2f}% ved amount "
                f"{assessed_amount:g}."
            )

        return TransactionCostAssessmentV3(
            severity=severity,
            amount=assessed_amount,
            long_total_cost_pct=long_pct,
            short_total_cost_pct=short_pct,
            long_commission=long_commission,
            short_commission=short_commission,
            commission_currency=currency,
            assumptions=assumptions,
            detail=detail,
        )
    except Exception as exc:
        return TransactionCostAssessmentV3(
            severity="RED",
            amount=float(amount or 0.0),
            long_total_cost_pct=None,
            short_total_cost_pct=None,
            long_commission=None,
            short_commission=None,
            commission_currency=None,
            assumptions=(),
            detail=(
                "Kostnad kunne ikke verifiseres mot Saxo; LIVE sperret "
                f"({type(exc).__name__}: {exc})."
            ),
        )


__all__ = [
    "COST_WARN_TOTAL_PCT_V3",
    "COST_BLOCK_TOTAL_PCT_V3",
    "TransactionCostAssessmentV3",
    "assess_transaction_cost_v3",
]
