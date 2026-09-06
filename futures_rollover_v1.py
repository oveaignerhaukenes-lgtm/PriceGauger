from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import logging
from typing import Any

from database import connect
from instrument_registry_v2 import (
    InstrumentSourceV2,
    ensure_instrument_source_v2,
    ensure_instrument_v2,
    list_subscribed_sources_v2,
    resolve_instrument_source_v2,
    set_collection_subscription_v2,
)
from saxo_provider import SaxoClient, SaxoInstrument, configured_client, select_contract_for_timestamp


LOGGER = logging.getLogger("pricegauger.futures_rollover_v1")
FUTURES_ASSET_TYPES_V1 = frozenset({"ContractFutures", "CfdOnFutures"})
DEFAULT_ROLL_LEAD_DAYS_V1 = 5


@dataclass(frozen=True, slots=True)
class FuturesRolloverEventV1:
    rollover_id: int
    market_id: int
    old_instrument_id: int
    new_instrument_id: int
    provider: str
    old_provider_instrument_id: str
    new_provider_instrument_id: str
    old_symbol: str | None
    new_symbol: str | None
    occurred_at: datetime
    reason: str
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class FuturesRolloverSummaryV1:
    checked: int = 0
    eligible: int = 0
    rolled: int = 0
    unchanged: int = 0
    failed: int = 0


def _as_utc(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


def _integer(value: Any) -> int | None:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _candidate_from_primary_listing(
    client: SaxoClient,
    source: InstrumentSourceV2,
    *,
    current_details: dict[str, Any],
    now: datetime,
) -> SaxoInstrument | None:
    current_uic = _integer(source.provider_instrument_id)
    primary_uic = _integer(current_details.get("PrimaryListing"))
    if primary_uic is not None and primary_uic != current_uic:
        return SaxoInstrument(
            asset=source.market_name,
            uic=primary_uic,
            asset_type=str(source.asset_type or "ContractFutures"),
        )

    metadata = source.metadata or {}
    continuous_uic = _integer(
        metadata.get("continuous_futures_uic")
        or metadata.get("continuous_uic")
        or metadata.get("futures_space_uic")
    )
    if continuous_uic is None:
        return None
    try:
        contracts = client.future_space(continuous_uic)
        candidate = select_contract_for_timestamp(
            contracts,
            now,
            minimum_days_to_expiry=2,
        )
    except Exception:
        return None
    if current_uic is not None and int(candidate.uic) == current_uic:
        return None
    return SaxoInstrument(
        asset=source.market_name,
        uic=int(candidate.uic),
        asset_type=str(candidate.asset_type or source.asset_type or "ContractFutures"),
        symbol=str(candidate.symbol or ""),
        description=str(candidate.description or ""),
        expiry=candidate.expiry,
        price_multiplier=float(source.price_multiplier or 1.0),
    )


def _roll_is_due(
    current_details: dict[str, Any],
    source: InstrumentSourceV2,
    *,
    now: datetime,
    roll_lead_days: int,
) -> tuple[bool, str]:
    expiry = _as_utc(
        current_details.get("ExpiryDateTime")
        or current_details.get("ExpiryDate")
        or (source.metadata or {}).get("expiry")
    )
    if current_details.get("IsTradable") is False:
        return True, "CURRENT_NOT_TRADABLE"
    if expiry is not None and expiry <= now:
        return True, "CURRENT_EXPIRED"
    if expiry is not None and expiry <= now + timedelta(days=max(0, int(roll_lead_days))):
        return True, "EXPIRY_WINDOW"
    return False, "NOT_DUE"


def _candidate_details(client: SaxoClient, candidate: SaxoInstrument) -> dict[str, Any]:
    details = client.instrument_details(candidate)
    if not isinstance(details, dict):
        raise ValueError("candidate details were not an object")
    if details.get("IsTradable") is False:
        raise ValueError(f"candidate UIC {candidate.uic} is not tradable")
    return details


def _record_rollover_event(
    *,
    source: InstrumentSourceV2,
    new_instrument_id: int,
    candidate: SaxoInstrument,
    old_symbol: str | None,
    new_symbol: str | None,
    occurred_at: datetime,
    reason: str,
    metadata: dict[str, Any],
) -> None:
    payload = json.dumps(metadata, sort_keys=True, separators=(",", ":"))
    with connect() as db:
        placeholder = "?::jsonb" if db.is_postgres else "?"
        db.execute(
            f"""
            INSERT INTO pg_v2_instrument_rollovers
                (market_id, old_instrument_id, new_instrument_id, provider,
                 old_provider_instrument_id, new_provider_instrument_id,
                 old_symbol, new_symbol, occurred_at, reason, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, {placeholder})
            ON CONFLICT (provider, old_provider_instrument_id, new_provider_instrument_id)
            DO NOTHING
            """,
            (
                int(source.market_id),
                int(source.instrument_id),
                int(new_instrument_id),
                str(source.provider),
                str(source.provider_instrument_id),
                str(candidate.uic),
                old_symbol,
                new_symbol,
                occurred_at,
                str(reason),
                payload,
            ),
        )


def _apply_rollover(
    *,
    source: InstrumentSourceV2,
    candidate: SaxoInstrument,
    candidate_details: dict[str, Any],
    occurred_at: datetime,
    reason: str,
) -> int:
    symbol = str(candidate_details.get("Symbol") or candidate.symbol or "").strip()
    description = str(candidate_details.get("Description") or candidate.description or "").strip()
    expiry = candidate_details.get("ExpiryDateTime") or candidate_details.get("ExpiryDate") or candidate.expiry

    try:
        existing = resolve_instrument_source_v2(
            provider="saxo",
            provider_instrument_id=int(candidate.uic),
            require_subscription=False,
        )
    except LookupError:
        existing = None

    if existing is not None:
        if int(existing.market_id) != int(source.market_id):
            raise ValueError(
                f"candidate UIC {candidate.uic} is already mapped to another canonical market"
            )
        new_instrument_id = int(existing.instrument_id)
    else:
        display_name = description or symbol or f"{source.market_name} · UIC {candidate.uic}"
        new_instrument_id = ensure_instrument_v2(
            market_id=int(source.market_id),
            instrument_type=str(source.instrument_type),
            display_name=display_name,
        )
        metadata = dict(source.metadata or {})
        metadata.update(
            {
                "description": description or display_name,
                "expiry": str(expiry) if expiry else None,
                "rollover_from_uic": str(source.provider_instrument_id),
                "rollover_reason": reason,
            }
        )
        ensure_instrument_source_v2(
            instrument_id=int(new_instrument_id),
            provider="saxo",
            provider_instrument_id=int(candidate.uic),
            asset_type=str(candidate.asset_type or source.asset_type or "ContractFutures"),
            symbol=symbol or None,
            price_multiplier=float(source.price_multiplier or 1.0),
            metadata=metadata,
        )

    # Collection authority rolls to the new immutable contract identity. Execution
    # authority does not: any LIVE controller remains bound to its exact old UIC and
    # must go through the normal close/FLAT/admission lifecycle before a new product
    # can be traded.
    set_collection_subscription_v2(instrument_id=int(source.instrument_id), enabled=False)
    set_collection_subscription_v2(instrument_id=int(new_instrument_id), enabled=True)
    _record_rollover_event(
        source=source,
        new_instrument_id=int(new_instrument_id),
        candidate=candidate,
        old_symbol=str(source.symbol or "") or None,
        new_symbol=symbol or str(existing.symbol if existing else "") or None,
        occurred_at=occurred_at,
        reason=reason,
        metadata={
            "old_expiry": (source.metadata or {}).get("expiry"),
            "new_expiry": str(expiry) if expiry else None,
            "selection": "SAXO_PRIMARY_LISTING_OR_FUTURES_SPACE",
        },
    )
    return int(new_instrument_id)


def resolve_saxo_futures_rollovers_once_v1(
    *,
    client: SaxoClient | None = None,
    now: datetime | None = None,
    roll_lead_days: int = DEFAULT_ROLL_LEAD_DAYS_V1,
) -> FuturesRolloverSummaryV1:
    """Roll subscribed Saxo futures collection to the broker's active front contract.

    The resolver is generic across canonical markets. It first trusts Saxo's
    ``PrimaryListing`` for expiring instruments (documented as the next expiring
    instance), then optionally falls back to an explicitly persisted continuous
    futures-space UIC. It changes collection identity only; it never mutates an
    AutoManager/AutoTrader LIVE controller, order, position or Product Admission.
    """

    sax = client or configured_client()
    if sax is None:
        return FuturesRolloverSummaryV1()
    observed_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    checked = eligible = rolled = unchanged = failed = 0
    for source in list_subscribed_sources_v2(provider="saxo"):
        if str(source.asset_type or "") not in FUTURES_ASSET_TYPES_V1:
            continue
        checked += 1
        try:
            current_uic = _integer(source.provider_instrument_id)
            if current_uic is None:
                raise ValueError(f"invalid current futures UIC {source.provider_instrument_id!r}")
            current = SaxoInstrument(
                asset=source.market_name,
                uic=current_uic,
                asset_type=str(source.asset_type),
                symbol=str(source.symbol or ""),
                description=str((source.metadata or {}).get("description") or source.display_name or ""),
                expiry=str((source.metadata or {}).get("expiry") or "") or None,
                price_multiplier=float(source.price_multiplier or 1.0),
            )
            details = sax.instrument_details(current)
            due, reason = _roll_is_due(details, source, now=observed_at, roll_lead_days=roll_lead_days)
            if not due:
                unchanged += 1
                continue
            eligible += 1
            candidate = _candidate_from_primary_listing(
                sax,
                source,
                current_details=details,
                now=observed_at,
            )
            if candidate is None:
                raise ValueError("no next futures contract could be resolved")
            candidate_details = _candidate_details(sax, candidate)
            candidate_expiry = _as_utc(
                candidate_details.get("ExpiryDateTime") or candidate_details.get("ExpiryDate") or candidate.expiry
            )
            if candidate_expiry is not None and candidate_expiry <= observed_at:
                raise ValueError(f"candidate UIC {candidate.uic} is already expired")
            new_id = _apply_rollover(
                source=source,
                candidate=candidate,
                candidate_details=candidate_details,
                occurred_at=observed_at,
                reason=reason,
            )
            rolled += 1
            LOGGER.warning(
                "Futures collection rollover market=%s old_uic=%s new_uic=%s old_instrument_id=%s new_instrument_id=%s reason=%s",
                source.market_name,
                source.provider_instrument_id,
                candidate.uic,
                source.instrument_id,
                new_id,
                reason,
            )
        except Exception as exc:
            failed += 1
            LOGGER.warning(
                "Futures rollover check failed market=%s uic=%s: %s",
                source.market_name,
                source.provider_instrument_id,
                exc,
                exc_info=True,
            )
    return FuturesRolloverSummaryV1(
        checked=checked,
        eligible=eligible,
        rolled=rolled,
        unchanged=unchanged,
        failed=failed,
    )


def load_futures_rollover_events_v1(
    *,
    instrument_id: int | None = None,
    market_id: int | None = None,
    limit: int = 20,
) -> tuple[FuturesRolloverEventV1, ...]:
    where: list[str] = []
    params: list[Any] = []
    if instrument_id is not None:
        where.append("(old_instrument_id = ? OR new_instrument_id = ?)")
        params.extend((int(instrument_id), int(instrument_id)))
    if market_id is not None:
        where.append("market_id = ?")
        params.append(int(market_id))
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    params.append(max(1, min(int(limit), 200)))
    with connect() as db:
        rows = db.execute(
            f"""
            SELECT rollover_id, market_id, old_instrument_id, new_instrument_id,
                   provider, old_provider_instrument_id, new_provider_instrument_id,
                   old_symbol, new_symbol, occurred_at, reason, metadata_json
            FROM pg_v2_instrument_rollovers
            {clause}
            ORDER BY occurred_at DESC, rollover_id DESC
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()
    events: list[FuturesRolloverEventV1] = []
    for row in rows:
        get = (lambda key, index: row[key] if isinstance(row, dict) else row[index])
        raw_meta = get("metadata_json", 11)
        if isinstance(raw_meta, str):
            try:
                metadata = dict(json.loads(raw_meta) or {})
            except Exception:
                metadata = {}
        else:
            metadata = dict(raw_meta or {})
        occurred = _as_utc(get("occurred_at", 9)) or datetime.now(timezone.utc)
        events.append(
            FuturesRolloverEventV1(
                rollover_id=int(get("rollover_id", 0)),
                market_id=int(get("market_id", 1)),
                old_instrument_id=int(get("old_instrument_id", 2)),
                new_instrument_id=int(get("new_instrument_id", 3)),
                provider=str(get("provider", 4)),
                old_provider_instrument_id=str(get("old_provider_instrument_id", 5)),
                new_provider_instrument_id=str(get("new_provider_instrument_id", 6)),
                old_symbol=str(get("old_symbol", 7) or "") or None,
                new_symbol=str(get("new_symbol", 8) or "") or None,
                occurred_at=occurred,
                reason=str(get("reason", 10)),
                metadata=metadata,
            )
        )
    return tuple(events)


__all__ = [
    "DEFAULT_ROLL_LEAD_DAYS_V1",
    "FUTURES_ASSET_TYPES_V1",
    "FuturesRolloverEventV1",
    "FuturesRolloverSummaryV1",
    "load_futures_rollover_events_v1",
    "resolve_saxo_futures_rollovers_once_v1",
]
