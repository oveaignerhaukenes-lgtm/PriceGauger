"""Strict read-only Saxo REST adapter with an injected GET transport.

Uses existing PG V3-verified Saxo endpoints. It deliberately has no OAuth
secrets, session.post, trading precheck or order-submit surface; a future
authenticated Saxo transport may provide only the GET callable here.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Callable, Mapping, Any

from .domain import SaxoBoundary


JsonObject = Mapping[str, Any]
GetRequest = Callable[[str, Mapping[str, Any]], JsonObject]


@dataclass(frozen=True, slots=True)
class SaxoAccount:
    account_id: str
    account_key: str
    client_key: str
    currency: str


@dataclass(frozen=True, slots=True)
class SaxoBalance:
    account_id: str
    currency: str
    total_value: Decimal
    cash_balance: Decimal | None
    calculation_reliability: str


def _numeric(value: Any) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError("Saxo numeric value absent or invalid")
    try:
        number = Decimal(str(value))
    except (TypeError, InvalidOperation) as exc:
        raise ValueError("Saxo numeric value invalid") from exc
    if not number.is_finite():
        raise ValueError("Saxo numeric value must be finite")
    return number


class SaxoReadOnlyGateway:
    """Exact account-scoped GETs; never assumes that client-wide data is local."""

    def __init__(self, get: GetRequest):
        self._get = get

    def accounts(self) -> tuple[SaxoAccount, ...]:
        raw = self._get("port/v1/accounts/me", {})
        if not isinstance(raw, Mapping) or raw.get("__next"):
            raise ValueError("Saxo accounts response missing or paginated")
        rows = raw.get("Data")
        if not isinstance(rows, list):
            raise ValueError("Saxo accounts must be a list")
        accounts = []
        seen = set()
        for row in rows:
            if not isinstance(row, Mapping):
                raise ValueError("Malformed Saxo account")
            aid = str(row.get("AccountId") or "").strip()
            account_key = str(row.get("AccountKey") or "").strip()
            client_key = str(row.get("ClientKey") or "").strip()
            currency = str(row.get("Currency") or "").strip().upper()
            if not all((aid, account_key, client_key, currency)) or aid in seen:
                raise ValueError("Saxo account boundary incomplete/duplicated")
            if len(currency) != 3:
                raise ValueError("Invalid Saxo account currency")
            seen.add(aid)
            accounts.append(SaxoAccount(aid, account_key, client_key, currency))
        return tuple(accounts)

    def _exact_account(self, account_id: str) -> SaxoAccount:
        matches = [a for a in self.accounts() if a.account_id == account_id]
        if len(matches) != 1:
            raise ValueError("Exact Saxo account unavailable")
        return matches[0]

    def balance(self, *, account_id: str) -> SaxoBalance:
        account = self._exact_account(account_id)
        result = self._get("port/v1/balances", {
            "AccountKey": account.account_key, "ClientKey": account.client_key,
        })
        if not isinstance(result, Mapping):
            raise ValueError("Malformed Saxo balance")
        if result.get("AccountId") is not None and str(result["AccountId"]) != account.account_id:
            raise ValueError("Saxo balance account mismatch")
        if str(result.get("Currency") or "").upper() != account.currency:
            raise ValueError("Saxo balance currency mismatch")
        cash = result.get("CashBalance")
        return SaxoBalance(
            account.account_id, account.currency,
            _numeric(result.get("TotalValue")),
            _numeric(cash) if cash is not None else None,
            str(result.get("CalculationReliability") or "UNVERIFIED"),
        )

    def net_positions(self, *, boundary: SaxoBoundary) -> tuple[dict[str, Any], ...]:
        account = self._exact_account(boundary.account_id)
        result = self._get("port/v1/netpositions", {
            "AccountKey": account.account_key,
            "ClientKey": account.client_key,
            "Uic": boundary.uic,
            "AssetType": boundary.asset_type,
            "$top": 1000,
            "FieldGroups": "NetPositionBase,NetPositionView",
        })
        if not isinstance(result, Mapping) or result.get("__next"):
            raise ValueError("Saxo net position result incomplete")
        rows = result.get("Data")
        if not isinstance(rows, list):
            raise ValueError("Saxo net positions must be a list")
        matched = []
        for row in rows:
            if not isinstance(row, Mapping):
                raise ValueError("Malformed Saxo net position")
            base = row.get("NetPositionBase")
            if not isinstance(base, Mapping):
                raise ValueError("Saxo net position base missing")
            uic = base.get("Uic")
            try:
                parsed_uic = int(uic)
            except (TypeError, ValueError) as exc:
                raise ValueError("Saxo net position UIC missing") from exc
            if parsed_uic != boundary.uic or str(base.get("AssetType") or "") != boundary.asset_type:
                raise ValueError("Saxo net position response crossed product boundary")
            # Reject a conflicting explicit account rather than incorrectly
            # attributing another broker account's inventory to this strategy.
            explicit_account = row.get("AccountId", base.get("AccountId"))
            if explicit_account is not None and str(explicit_account) != account.account_id:
                raise ValueError("Saxo net position response crossed account boundary")
            matched.append(dict(row))
        return tuple(matched)
