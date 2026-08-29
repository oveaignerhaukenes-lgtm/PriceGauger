from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from autotrader_risk_control_v2 import PositionObservationV2, _position_observations_v2
from database import using_postgres
from instrument_onboarding_v2 import (
    InstrumentOnboardingResultV2,
    SaxoInstrumentOnboardingRequestV2,
    onboard_saxo_instrument_v2,
)
from instrument_registry_v2 import (
    InstrumentSourceV2,
    list_subscribed_sources_v2,
    resolve_instrument_source_v2,
    set_collection_subscription_v2,
)
from saxo_product_explorer import category_for_asset_type
from saxo_provider import configured_client


LOGGER = logging.getLogger("pricegauger.saxo_open_position_discovery_v2")
DISCOVERY_ORIGIN = "SAXO_OPEN_POSITION"


@dataclass(frozen=True, slots=True)
class SaxoOpenPositionDiscoverySummaryV2:
    observed_products: int
    already_subscribed: int
    subscriptions_reactivated: int
    onboarded: int
    failed: int


@dataclass(frozen=True, slots=True)
class SaxoOpenPositionIdentityV2:
    account_id: str
    uic: int
    asset_type: str


@dataclass(frozen=True, slots=True)
class SaxoReferenceIdentityV2:
    uic: int
    asset_type: str
    description: str
    symbol: str
    currency: str | None
    exchange: str | None
    underlying_asset_type: str | None
    tradable_as: tuple[str, ...]
    raw: dict[str, Any]


def _unique_products(
    observations: tuple[PositionObservationV2, ...],
) -> tuple[SaxoOpenPositionIdentityV2, ...]:
    identities = {
        (str(item.account_id).strip(), int(item.uic), str(item.asset_type).strip())
        for item in observations
        if str(item.account_id).strip() and int(item.uic) > 0 and str(item.asset_type).strip()
    }
    return tuple(
        SaxoOpenPositionIdentityV2(account_id=account_id, uic=uic, asset_type=asset_type)
        for account_id, uic, asset_type in sorted(identities)
    )


def _account_keys(client) -> dict[str, str]:
    payload = client._get("port/v1/accounts/me")
    rows = payload.get("Data") or []
    if not isinstance(rows, list):
        raise RuntimeError("Saxo account list had invalid Data format")
    result: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        account_id = str(row.get("AccountId") or "").strip()
        account_key = str(row.get("AccountKey") or "").strip()
        if account_id and account_key and bool(row.get("Active", True)):
            result[account_id] = account_key
    return result


def _tuple_strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value if item is not None)


def _load_reference_identity(
    client,
    *,
    product: SaxoOpenPositionIdentityV2,
    account_key: str,
) -> SaxoReferenceIdentityV2:
    payload = client._get(
        f"ref/v1/instruments/details/{product.uic}/{product.asset_type}",
        params={"AccountKey": account_key, "FieldGroups": "OrderSetting"},
    )
    if not isinstance(payload, dict):
        raise RuntimeError("Saxo instrument-details response was not an object")

    raw_uic = payload.get("Uic", payload.get("Identifier"))
    try:
        resolved_uic = int(raw_uic)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Saxo instrument details did not return an exact UIC") from exc
    resolved_asset_type = str(payload.get("AssetType") or "").strip()
    if resolved_uic != product.uic or resolved_asset_type != product.asset_type:
        raise ValueError(
            "Saxo Reference Data identity did not match the open position; refusing canonical onboarding"
        )

    description = str(payload.get("Description") or "").strip()
    symbol = str(payload.get("Symbol") or "").strip()
    if not description and not symbol:
        raise ValueError("Saxo Reference Data returned no description or symbol")
    exchange = payload.get("Exchange") if isinstance(payload.get("Exchange"), dict) else {}
    return SaxoReferenceIdentityV2(
        uic=resolved_uic,
        asset_type=resolved_asset_type,
        description=description,
        symbol=symbol,
        currency=(
            str(payload.get("CurrencyCode") or payload.get("PriceCurrency") or "").strip().upper()
            or None
        ),
        exchange=(str(exchange.get("Name") or exchange.get("ExchangeId") or "").strip() or None),
        underlying_asset_type=(str(payload.get("UnderlyingAssetType") or "").strip() or None),
        tradable_as=_tuple_strings(payload.get("TradableAs")),
        raw=dict(payload),
    )


def _market_name(reference: SaxoReferenceIdentityV2) -> str:
    # Auto-discovery never fuzzy-merges an externally opened Saxo product into an
    # existing canonical market. Exact provider identity wins over semantic
    # similarity; a later explicit Product Browser workflow may deliberately
    # consolidate markets if desired.
    label = reference.description or reference.symbol or reference.asset_type
    return f"{label} · Saxo {reference.uic}"


def _display_name(reference: SaxoReferenceIdentityV2) -> str:
    label = reference.description or reference.symbol or reference.asset_type
    return f"{label} [{reference.asset_type}:{reference.uic}]"


def _existing_source(uic: int) -> InstrumentSourceV2 | None:
    try:
        return resolve_instrument_source_v2(
            provider="saxo",
            provider_instrument_id=str(int(uic)),
            require_subscription=False,
        )
    except LookupError:
        return None


def _subscribed_source(uic: int) -> InstrumentSourceV2 | None:
    try:
        return resolve_instrument_source_v2(
            provider="saxo",
            provider_instrument_id=str(int(uic)),
            require_subscription=True,
        )
    except LookupError:
        return None


def _reactivate_existing_source(
    source: InstrumentSourceV2,
    *,
    asset_type: str,
) -> None:
    if source.asset_type and str(source.asset_type) != str(asset_type):
        raise ValueError("existing Saxo provider identity has a different AssetType")
    conflicts = tuple(
        item
        for item in list_subscribed_sources_v2(provider="saxo")
        if int(item.market_id) == int(source.market_id)
        and int(item.instrument_id) != int(source.instrument_id)
    )
    if conflicts:
        raise ValueError(
            "canonical market already has a different active Saxo feed; refusing automatic replacement"
        )
    set_collection_subscription_v2(instrument_id=source.instrument_id, enabled=True)


def _onboard_reference(
    product: SaxoOpenPositionIdentityV2,
    reference: SaxoReferenceIdentityV2,
) -> InstrumentOnboardingResultV2:
    metadata = {
        "discovery_origin": DISCOVERY_ORIGIN,
        "saxo_account_id": product.account_id,
        "description": reference.description,
        "symbol": reference.symbol,
        "currency": reference.currency,
        "exchange": reference.exchange,
        "underlying_asset_type": reference.underlying_asset_type,
        "tradable_as": list(reference.tradable_as),
    }
    return onboard_saxo_instrument_v2(
        SaxoInstrumentOnboardingRequestV2(
            market_name=_market_name(reference),
            market_category=category_for_asset_type(reference.asset_type),
            display_name=_display_name(reference),
            uic=reference.uic,
            asset_type=reference.asset_type,
            symbol=reference.symbol or None,
            price_multiplier=1.0,
            metadata=metadata,
        )
    )


def discover_open_saxo_positions_once_v2(client=None) -> SaxoOpenPositionDiscoverySummaryV2:
    """Discover externally opened Saxo positions into the canonical v2 registry.

    Discovery grants no AutoManage or order authority. It only establishes exact
    provider identity and an enabled 1m collection subscription so the existing
    realtime/Technical-Core/TradingDesk path can ingest the product. Strategy
    enrollment remains an explicit user action in TradingDesk.
    """
    if not using_postgres():
        return SaxoOpenPositionDiscoverySummaryV2(0, 0, 0, 0, 0)
    client = client or configured_client()
    if client is None:
        return SaxoOpenPositionDiscoverySummaryV2(0, 0, 0, 0, 0)

    products = _unique_products(_position_observations_v2(client))
    if not products:
        return SaxoOpenPositionDiscoverySummaryV2(0, 0, 0, 0, 0)

    known = 0
    reactivated = 0
    onboarded = 0
    failed = 0
    account_keys: dict[str, str] | None = None

    for product in products:
        try:
            subscribed = _subscribed_source(product.uic)
            if subscribed is not None:
                if subscribed.asset_type and str(subscribed.asset_type) != product.asset_type:
                    raise ValueError("subscribed Saxo provider identity has a different AssetType")
                known += 1
                continue

            existing = _existing_source(product.uic)
            if existing is not None:
                _reactivate_existing_source(existing, asset_type=product.asset_type)
                reactivated += 1
                LOGGER.info(
                    "Saxo open-position source reactivated account=%s uic=%s asset_type=%s canonical_market=%s",
                    product.account_id,
                    product.uic,
                    product.asset_type,
                    existing.market_name,
                )
                continue

            if account_keys is None:
                account_keys = _account_keys(client)
            account_key = account_keys.get(product.account_id)
            if not account_key:
                raise RuntimeError("could not resolve AccountKey for open Saxo position")
            reference = _load_reference_identity(
                client,
                product=product,
                account_key=account_key,
            )
            result = _onboard_reference(product, reference)
            onboarded += 1
            LOGGER.info(
                "Saxo open-position discovered account=%s uic=%s asset_type=%s symbol=%s description=%s canonical_market=%s instrument_id=%s",
                product.account_id,
                product.uic,
                product.asset_type,
                reference.symbol or "none",
                reference.description or "none",
                result.market_name,
                result.instrument_id,
            )
        except Exception as exc:
            failed += 1
            LOGGER.warning(
                "Saxo open-position discovery failed account=%s uic=%s asset_type=%s: %s",
                product.account_id,
                product.uic,
                product.asset_type,
                exc,
                exc_info=True,
            )

    return SaxoOpenPositionDiscoverySummaryV2(
        observed_products=len(products),
        already_subscribed=known,
        subscriptions_reactivated=reactivated,
        onboarded=onboarded,
        failed=failed,
    )


__all__ = [
    "DISCOVERY_ORIGIN",
    "SaxoOpenPositionDiscoverySummaryV2",
    "SaxoOpenPositionIdentityV2",
    "SaxoReferenceIdentityV2",
    "discover_open_saxo_positions_once_v2",
]
