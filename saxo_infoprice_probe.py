from __future__ import annotations

from dataclasses import dataclass
import hashlib
import logging
import time
from typing import Any, Callable, Mapping

from saxo_provider import SaxoClient, SaxoInstrument


LOGGER = logging.getLogger("pricegauger.saxo_infoprice_probe")
DEFAULT_PROBE_SECONDS = 300
FIELD_GROUPS = "InstrumentPriceDetails,PriceInfo,PriceInfoDetails,Quote"


@dataclass(frozen=True, slots=True)
class InfoPriceDiagnostic:
    market: str
    uic: int
    asset_type: str
    last_updated: str | None
    is_market_open: bool | None
    delayed_by_minutes: float | None
    error_code: str | None
    price_type_bid: str | None
    price_type_ask: str | None
    bid: float | None
    ask: float | None
    mid: float | None
    last_traded: float | None


@dataclass(frozen=True, slots=True)
class SaxoIdentityDiagnostic:
    environment: str
    user_fingerprint: str
    client_fingerprint: str
    default_account_fingerprint: str
    active: bool | None
    market_data_terms_accepted: bool | None
    user_legal_asset_types: tuple[str, ...]
    client_legal_asset_types: tuple[str, ...]
    account_count: int
    account_types: tuple[str, ...]
    trial_account_count: int
    entitlement_exchange_count: int
    entitlement_modes: tuple[str, ...]


def _number(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _fingerprint(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "none"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(sorted(str(item) for item in value if item is not None))


def _diagnostic_from_row(*, market: str, instrument: SaxoInstrument, row: Mapping[str, Any]) -> InfoPriceDiagnostic:
    quote = row.get("Quote") if isinstance(row.get("Quote"), Mapping) else {}
    details = row.get("InstrumentPriceDetails") if isinstance(row.get("InstrumentPriceDetails"), Mapping) else {}
    price_details = row.get("PriceInfoDetails") if isinstance(row.get("PriceInfoDetails"), Mapping) else {}
    is_open = details.get("IsMarketOpen")
    return InfoPriceDiagnostic(
        market=market,
        uic=instrument.uic,
        asset_type=instrument.asset_type,
        last_updated=None if row.get("LastUpdated") is None else str(row.get("LastUpdated")),
        is_market_open=is_open if isinstance(is_open, bool) else None,
        delayed_by_minutes=_number(quote.get("DelayedByMinutes")),
        error_code=None if quote.get("ErrorCode") is None else str(quote.get("ErrorCode")),
        price_type_bid=None if quote.get("PriceTypeBid") is None else str(quote.get("PriceTypeBid")),
        price_type_ask=None if quote.get("PriceTypeAsk") is None else str(quote.get("PriceTypeAsk")),
        bid=_number(quote.get("Bid")),
        ask=_number(quote.get("Ask")),
        mid=_number(quote.get("Mid")),
        last_traded=_number(price_details.get("LastTraded")),
    )


def fetch_infoprice_diagnostics(
    *,
    client: SaxoClient,
    instruments: Mapping[str, SaxoInstrument],
) -> tuple[InfoPriceDiagnostic, ...]:
    """Read Saxo InfoPrices without changing collection or trading state."""
    grouped: dict[str, list[tuple[str, SaxoInstrument]]] = {}
    for market, instrument in instruments.items():
        grouped.setdefault(instrument.asset_type, []).append((market, instrument))

    diagnostics: list[InfoPriceDiagnostic] = []
    for asset_type, members in grouped.items():
        payload = client._get(  # noqa: SLF001 - diagnostic uses authenticated provider contract
            "trade/v1/infoprices/list",
            params={
                "AssetType": asset_type,
                "Uics": ",".join(str(instrument.uic) for _, instrument in members),
                "FieldGroups": FIELD_GROUPS,
            },
        )
        rows = payload.get("Data", []) if isinstance(payload, dict) else []
        by_uic = {
            int(row["Uic"]): row
            for row in rows
            if isinstance(row, Mapping) and row.get("Uic") is not None
        }
        for market, instrument in members:
            row = by_uic.get(int(instrument.uic))
            if row is None:
                diagnostics.append(
                    InfoPriceDiagnostic(
                        market=market,
                        uic=instrument.uic,
                        asset_type=instrument.asset_type,
                        last_updated=None,
                        is_market_open=None,
                        delayed_by_minutes=None,
                        error_code="MISSING_FROM_RESPONSE",
                        price_type_bid=None,
                        price_type_ask=None,
                        bid=None,
                        ask=None,
                        mid=None,
                        last_traded=None,
                    )
                )
                continue
            diagnostics.append(_diagnostic_from_row(market=market, instrument=instrument, row=row))
    return tuple(diagnostics)


def fetch_identity_diagnostic(*, client: SaxoClient) -> SaxoIdentityDiagnostic:
    """Read authenticated Saxo identity/feed metadata without exposing account identifiers."""
    user = client._get("port/v1/users/me")  # noqa: SLF001
    client_row = client._get("port/v1/clients/me")  # noqa: SLF001
    accounts_payload = client._get("port/v1/accounts/me", params={"$top": 100})  # noqa: SLF001
    entitlement_payload = client._get(  # noqa: SLF001
        "port/v1/users/me/entitlements",
        params={"EntitlementFieldSet": "Default"},
    )

    accounts = accounts_payload.get("Data", []) if isinstance(accounts_payload, dict) else []
    account_rows = [row for row in accounts if isinstance(row, Mapping)]
    entitlement_rows = (
        entitlement_payload.get("Data", []) if isinstance(entitlement_payload, dict) else []
    )
    modes: set[str] = set()
    exchange_count = 0
    for row in entitlement_rows:
        if not isinstance(row, Mapping):
            continue
        exchange_count += 1
        groups = row.get("Entitlements")
        if not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, Mapping):
                continue
            for mode, asset_types in group.items():
                if isinstance(asset_types, list) and asset_types:
                    modes.add(f"{mode}:{','.join(sorted(str(item) for item in asset_types))}")

    environment = "live" if "/openapi" in client.base_url and "/sim/openapi" not in client.base_url else "sim"
    active = user.get("Active")
    terms = user.get("MarketDataViaOpenApiTermsAccepted")
    return SaxoIdentityDiagnostic(
        environment=environment,
        user_fingerprint=_fingerprint(user.get("UserKey") or user.get("UserId")),
        client_fingerprint=_fingerprint(user.get("ClientKey") or client_row.get("ClientKey")),
        default_account_fingerprint=_fingerprint(client_row.get("DefaultAccountKey")),
        active=active if isinstance(active, bool) else None,
        market_data_terms_accepted=terms if isinstance(terms, bool) else None,
        user_legal_asset_types=_string_tuple(user.get("LegalAssetTypes")),
        client_legal_asset_types=_string_tuple(client_row.get("LegalAssetTypes")),
        account_count=len(account_rows),
        account_types=tuple(sorted({str(row.get("AccountType")) for row in account_rows if row.get("AccountType")})),
        trial_account_count=sum(1 for row in account_rows if row.get("IsTrialAccount") is True),
        entitlement_exchange_count=exchange_count,
        entitlement_modes=tuple(sorted(modes)),
    )


def log_identity_diagnostic(*, client: SaxoClient) -> None:
    item = fetch_identity_diagnostic(client=client)
    LOGGER.info(
        "Saxo auth/feed diagnostic environment=%s user_fp=%s client_fp=%s default_account_fp=%s active=%s "
        "market_data_terms_accepted=%s user_legal_asset_types=%s client_legal_asset_types=%s "
        "account_count=%s account_types=%s trial_accounts=%s entitlement_exchanges=%s entitlement_modes=%s",
        item.environment,
        item.user_fingerprint,
        item.client_fingerprint,
        item.default_account_fingerprint,
        item.active,
        item.market_data_terms_accepted,
        ",".join(item.user_legal_asset_types) or "none",
        ",".join(item.client_legal_asset_types) or "none",
        item.account_count,
        ",".join(item.account_types) or "none",
        item.trial_account_count,
        item.entitlement_exchange_count,
        ";".join(item.entitlement_modes) or "none",
    )


def log_infoprice_diagnostics(*, client: SaxoClient, instruments: Mapping[str, SaxoInstrument]) -> None:
    for item in fetch_infoprice_diagnostics(client=client, instruments=instruments):
        LOGGER.info(
            "Saxo InfoPrice diagnostic market=%s uic=%s asset_type=%s market_open=%s delayed_minutes=%s error_code=%s price_type_bid=%s price_type_ask=%s bid=%s ask=%s mid=%s last_traded=%s last_updated=%s",
            item.market,
            item.uic,
            item.asset_type,
            item.is_market_open,
            item.delayed_by_minutes,
            item.error_code,
            item.price_type_bid,
            item.price_type_ask,
            item.bid,
            item.ask,
            item.mid,
            item.last_traded,
            item.last_updated,
        )


def run_infoprice_probe_forever(
    *,
    client: SaxoClient,
    instruments: Mapping[str, SaxoInstrument],
    stop_requested: Callable[[], bool],
    interval_seconds: int = DEFAULT_PROBE_SECONDS,
) -> None:
    interval = max(60, int(interval_seconds))
    while not stop_requested():
        try:
            log_identity_diagnostic(client=client)
        except Exception as exc:
            LOGGER.warning("Saxo auth/feed diagnostic failed: %s", exc, exc_info=True)
        try:
            log_infoprice_diagnostics(client=client, instruments=instruments)
        except Exception as exc:
            LOGGER.warning("Saxo InfoPrice diagnostic failed: %s", exc, exc_info=True)
        for _ in range(interval):
            if stop_requested():
                return
            time.sleep(1)
