from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import time
from typing import Any, Iterable
from uuid import NAMESPACE_URL, uuid5

from autotrader_risk_control_v2 import _position_observations_v2
from database import connect, using_postgres
from instrument_registry_v2 import InstrumentSourceV2, list_subscribed_sources_v2, resolve_instrument_source_v2
from realtime_gap_repair import repair_recent_market_history
from realtime_market_data import RealtimeMarketDataStore
from saxo_provider import SaxoClient, SaxoInstrument, configured_client


LOGGER = logging.getLogger("pricegauger.futures_rollover_v1")
ROLLABLE_ASSET_TYPES = frozenset({"ContractFutures", "CfdOnFutures"})
ROLLOVER_ORIGIN = "FUTURES_ROLLOVER"
CHECK_INTERVAL_SECONDS = 15 * 60.0
FORCE_ROLL_DAYS = 2
LIQUIDITY_ROLL_WINDOW_DAYS = 21
LIQUIDITY_RATIO = 1.20
CANDIDATE_CHAIN_DEPTH = 3
VOLUME_HORIZON_MINUTES = 60
VOLUME_BAR_COUNT = 120
SEED_LOOKBACK_HOURS = 24 * 10
SEED_MAX_PAGES = 10
SEED_PAGE_SIZE = 1200

_LAST_CHECK_MONO: dict[int, float] = {}


def _utc(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class FuturesContractCandidateV1:
    uic: int
    asset_type: str
    symbol: str
    description: str
    expiry: datetime | None
    primary_listing: int | None
    is_tradable: bool | None
    volume_score: float | None = None

    @property
    def instrument(self) -> SaxoInstrument:
        return SaxoInstrument(
            asset=self.description or self.symbol or str(self.uic),
            uic=int(self.uic),
            asset_type=self.asset_type,
            symbol=self.symbol,
            description=self.description,
            expiry=self.expiry.isoformat() if self.expiry is not None else None,
        )


@dataclass(frozen=True, slots=True)
class FuturesRolloverEventV1:
    event_id: str
    market_id: int
    market_name: str
    status: str
    effective_at: datetime
    old_instrument_id: int
    new_instrument_id: int | None
    old_uic: int
    new_uic: int | None
    old_symbol: str
    new_symbol: str | None
    old_expiry: datetime | None
    new_expiry: datetime | None
    selection_method: str
    block_reason: str | None


@dataclass(frozen=True, slots=True)
class FuturesRolloverSummaryV1:
    checked: int
    unchanged: int
    rolled: int
    blocked: int
    failed: int


def ensure_futures_rollover_schema_v1() -> None:
    if not using_postgres():
        return
    with connect() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS pg_v2_futures_rollover_events (
                event_id TEXT PRIMARY KEY,
                market_id BIGINT NOT NULL,
                market_name TEXT NOT NULL,
                status TEXT NOT NULL,
                detected_at TIMESTAMPTZ NOT NULL,
                effective_at TIMESTAMPTZ NOT NULL,
                old_instrument_id BIGINT NOT NULL,
                new_instrument_id BIGINT NULL,
                old_uic BIGINT NOT NULL,
                new_uic BIGINT NULL,
                old_symbol TEXT NOT NULL DEFAULT '',
                new_symbol TEXT NULL,
                old_expiry TIMESTAMPTZ NULL,
                new_expiry TIMESTAMPTZ NULL,
                selection_method TEXT NOT NULL,
                old_volume DOUBLE PRECISION NULL,
                new_volume DOUBLE PRECISION NULL,
                block_reason TEXT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        db.execute(
            """
            CREATE INDEX IF NOT EXISTS pg_v2_futures_rollover_market_time_idx
            ON pg_v2_futures_rollover_events(market_id, effective_at DESC)
            """
        )


def _contract_details(client: SaxoClient, *, uic: int, asset_type: str) -> FuturesContractCandidateV1:
    payload = client._get(f"ref/v1/instruments/details/{int(uic)}/{asset_type}")
    resolved_uic = int(payload.get("Uic") or payload.get("Identifier") or 0)
    resolved_asset_type = str(payload.get("AssetType") or "").strip()
    if resolved_uic != int(uic) or resolved_asset_type != asset_type:
        raise ValueError("Saxo futures details returned a different exact product identity")
    primary = payload.get("PrimaryListing")
    try:
        next_uic = int(primary) if primary not in (None, "") else None
    except (TypeError, ValueError):
        next_uic = None
    if next_uic == int(uic):
        next_uic = None
    tradable_raw = payload.get("IsTradable")
    return FuturesContractCandidateV1(
        uic=resolved_uic,
        asset_type=resolved_asset_type,
        symbol=str(payload.get("Symbol") or ""),
        description=str(payload.get("Description") or ""),
        expiry=_utc(payload.get("ExpiryDateTime") or payload.get("ExpiryDate")),
        primary_listing=next_uic,
        is_tradable=None if tradable_raw is None else bool(tradable_raw),
    )


def _candidate_chain(
    client: SaxoClient,
    *,
    source: InstrumentSourceV2,
) -> tuple[FuturesContractCandidateV1, ...]:
    asset_type = str(source.asset_type or "").strip()
    current_uic = int(source.provider_instrument_id)
    result: list[FuturesContractCandidateV1] = []
    seen: set[int] = set()
    uic: int | None = current_uic
    while uic is not None and len(result) < CANDIDATE_CHAIN_DEPTH and uic not in seen:
        seen.add(uic)
        candidate = _contract_details(client, uic=uic, asset_type=asset_type)
        result.append(candidate)
        uic = candidate.primary_listing

    if len(result) > 1:
        return tuple(result)

    # PrimaryListing is Saxo's normal forward link for expiring instruments. If a
    # legacy/expired product no longer exposes it, use an account-visible exact
    # AssetType search as a bounded recovery path and only accept later expiries.
    current_expiry = result[0].expiry if result else None
    try:
        discovered = client.search_instruments(source.market_name, asset_types=asset_type)
    except Exception:
        discovered = []
    for item in discovered:
        if int(item.uic) in seen or str(item.asset_type) != asset_type:
            continue
        expiry = _utc(item.expiry)
        if expiry is None or (current_expiry is not None and expiry <= current_expiry):
            continue
        try:
            candidate = _contract_details(client, uic=int(item.uic), asset_type=asset_type)
        except Exception:
            continue
        result.append(candidate)
        seen.add(candidate.uic)
        if len(result) >= CANDIDATE_CHAIN_DEPTH:
            break
    result.sort(key=lambda item: (item.expiry or datetime.max.replace(tzinfo=timezone.utc), item.uic))
    return tuple(result[:CANDIDATE_CHAIN_DEPTH])


def _with_volume(client: SaxoClient, candidate: FuturesContractCandidateV1) -> FuturesContractCandidateV1:
    score: float | None = None
    try:
        frame = client.chart(
            candidate.instrument,
            horizon_minutes=VOLUME_HORIZON_MINUTES,
            count=VOLUME_BAR_COUNT,
        )
        if "volume" in frame.columns:
            values = frame["volume"].dropna()
            if len(values):
                score = float(values.clip(lower=0).sum())
    except Exception:
        score = None
    return FuturesContractCandidateV1(
        uic=candidate.uic,
        asset_type=candidate.asset_type,
        symbol=candidate.symbol,
        description=candidate.description,
        expiry=candidate.expiry,
        primary_listing=candidate.primary_listing,
        is_tradable=candidate.is_tradable,
        volume_score=score,
    )


def select_futures_rollover_candidate_v1(
    candidates: Iterable[FuturesContractCandidateV1],
    *,
    now: datetime,
) -> tuple[FuturesContractCandidateV1, str]:
    rows = list(candidates)
    if not rows:
        raise ValueError("no futures rollover candidates")
    current = rows[0]
    if current.expiry is None:
        return current, "NO_EXPIRY_METADATA"

    eligible = [
        item
        for item in rows
        if item.expiry is not None
        and item.expiry > now
        and item.is_tradable is not False
    ]
    eligible.sort(key=lambda item: (item.expiry, item.uic))
    later = [item for item in eligible if item.uic != current.uic and item.expiry > current.expiry]
    if not later:
        return current, "NO_LATER_ELIGIBLE_CONTRACT"

    days_left = (current.expiry - now).total_seconds() / 86400.0
    if days_left <= FORCE_ROLL_DAYS:
        volume_candidates = [item for item in later if item.volume_score is not None and item.volume_score > 0]
        if volume_candidates:
            return max(volume_candidates, key=lambda item: float(item.volume_score or 0.0)), "FORCED_NEAR_EXPIRY_VOLUME"
        return later[0], "FORCED_NEAR_EXPIRY_FRONT"

    if days_left <= LIQUIDITY_ROLL_WINDOW_DAYS:
        current_volume = float(current.volume_score or 0.0)
        volume_candidates = [item for item in later if item.volume_score is not None and item.volume_score > 0]
        if volume_candidates:
            liquid = max(volume_candidates, key=lambda item: float(item.volume_score or 0.0))
            if current_volume <= 0.0 or float(liquid.volume_score or 0.0) >= current_volume * LIQUIDITY_RATIO:
                return liquid, "LIQUIDITY_MIGRATION"

    return current, "CURRENT_CONTRACT_RETAINS_LIQUIDITY"


def _live_controller_exists(*, uic: int, asset_type: str) -> bool:
    try:
        with connect() as db:
            row = db.execute(
                """
                SELECT 1
                FROM pg_v2_autotrader_strategy_enrollments
                WHERE enabled = TRUE
                  AND execution_mode = 'LIVE_MANAGE'
                  AND uic = ?
                  AND asset_type = ?
                LIMIT 1
                """,
                (int(uic), str(asset_type)),
            ).fetchone()
        return row is not None
    except Exception as exc:
        # Execution uncertainty must block an automatic contract switch.
        raise RuntimeError("could not verify active LIVE controller state") from exc


def _open_position_exists(observations: tuple[Any, ...], *, uic: int, asset_type: str) -> bool:
    return any(
        int(getattr(item, "uic", 0) or 0) == int(uic)
        and str(getattr(item, "asset_type", "") or "") == str(asset_type)
        for item in observations
    )


def _event_id(
    *,
    status: str,
    market_id: int,
    old_uic: int,
    new_uic: int | None,
    effective_at: datetime,
    block_reason: str | None,
) -> str:
    suffix = effective_at.date().isoformat() if status != "ROLLED" else effective_at.isoformat()
    return str(
        uuid5(
            NAMESPACE_URL,
            f"pg-futures-rollover-v1|{status}|{market_id}|{old_uic}|{new_uic}|{suffix}|{block_reason or ''}",
        )
    )


def _persist_event(
    *,
    source: InstrumentSourceV2,
    current: FuturesContractCandidateV1,
    selected: FuturesContractCandidateV1,
    status: str,
    selection_method: str,
    effective_at: datetime,
    new_instrument_id: int | None,
    block_reason: str | None = None,
) -> None:
    ensure_futures_rollover_schema_v1()
    event_id = _event_id(
        status=status,
        market_id=source.market_id,
        old_uic=current.uic,
        new_uic=selected.uic if selected.uic != current.uic else None,
        effective_at=effective_at,
        block_reason=block_reason,
    )
    with connect() as db:
        db.execute(
            """
            INSERT INTO pg_v2_futures_rollover_events(
                event_id, market_id, market_name, status, detected_at, effective_at,
                old_instrument_id, new_instrument_id, old_uic, new_uic,
                old_symbol, new_symbol, old_expiry, new_expiry, selection_method,
                old_volume, new_volume, block_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(event_id) DO NOTHING
            """,
            (
                event_id,
                int(source.market_id),
                source.market_name,
                status,
                effective_at,
                effective_at,
                int(source.instrument_id),
                None if new_instrument_id is None else int(new_instrument_id),
                int(current.uic),
                None if selected.uic == current.uic else int(selected.uic),
                current.symbol,
                None if selected.uic == current.uic else selected.symbol,
                current.expiry,
                selected.expiry,
                selection_method,
                current.volume_score,
                selected.volume_score,
                block_reason,
            ),
        )


def _switch_collection_source(
    *,
    source: InstrumentSourceV2,
    selected: FuturesContractCandidateV1,
    now: datetime,
    selection_method: str,
) -> InstrumentSourceV2:
    metadata = {
        "discovery_origin": ROLLOVER_ORIGIN,
        "rollover_from_uic": int(source.provider_instrument_id),
        "description": selected.description,
        "symbol": selected.symbol,
        "expiry": selected.expiry.isoformat() if selected.expiry is not None else None,
        "selection_method": selection_method,
        "rollover_detected_at": now.isoformat(),
    }
    display_name = f"{selected.description or selected.symbol or source.market_name} [{selected.asset_type}:{selected.uic}]"

    with connect() as db:
        market = db.execute(
            "SELECT market_id, category FROM pg_v2_markets WHERE market_id = ? AND active = TRUE",
            (int(source.market_id),),
        ).fetchone()
        if market is None:
            raise RuntimeError("canonical market disappeared during futures rollover")

        existing = db.execute(
            """
            SELECT s.instrument_id, i.market_id
            FROM pg_v2_instrument_sources s
            JOIN pg_v2_instruments i ON i.instrument_id = s.instrument_id AND i.active = TRUE
            WHERE s.provider = 'saxo' AND s.provider_instrument_id = ? AND s.active = TRUE
            ORDER BY s.instrument_source_id DESC
            LIMIT 1
            """,
            (str(int(selected.uic)),),
        ).fetchone()
        if existing is not None:
            new_instrument_id = int(existing["instrument_id"] if isinstance(existing, dict) else existing[0])
            existing_market_id = int(existing["market_id"] if isinstance(existing, dict) else existing[1])
            if existing_market_id != int(source.market_id):
                raise ValueError("next futures UIC is already mapped to a different canonical market")
        else:
            instrument = db.execute(
                """
                SELECT instrument_id FROM pg_v2_instruments
                WHERE market_id = ? AND instrument_type = ? AND display_name = ? AND active = TRUE
                ORDER BY instrument_id DESC LIMIT 1
                """,
                (int(source.market_id), selected.asset_type, display_name),
            ).fetchone()
            if instrument is None:
                db.execute(
                    """
                    INSERT INTO pg_v2_instruments(market_id, instrument_type, display_name, active)
                    VALUES (?, ?, ?, TRUE)
                    """,
                    (int(source.market_id), selected.asset_type, display_name),
                )
                instrument = db.execute(
                    """
                    SELECT instrument_id FROM pg_v2_instruments
                    WHERE market_id = ? AND instrument_type = ? AND display_name = ? AND active = TRUE
                    ORDER BY instrument_id DESC LIMIT 1
                    """,
                    (int(source.market_id), selected.asset_type, display_name),
                ).fetchone()
            new_instrument_id = int(instrument["instrument_id"] if isinstance(instrument, dict) else instrument[0])
            import json
            metadata_json = json.dumps(metadata, sort_keys=True, separators=(",", ":"))
            json_placeholder = "?::jsonb" if db.is_postgres else "?"
            db.execute(
                f"""
                INSERT INTO pg_v2_instrument_sources(
                    instrument_id, provider, provider_instrument_id, asset_type,
                    symbol, price_multiplier, metadata_json, active
                ) VALUES (?, 'saxo', ?, ?, ?, ?, {json_placeholder}, TRUE)
                """,
                (
                    new_instrument_id,
                    str(int(selected.uic)),
                    selected.asset_type,
                    selected.symbol or None,
                    1.0 if source.price_multiplier is None else float(source.price_multiplier),
                    metadata_json,
                ),
            )

        db.execute(
            """
            UPDATE pg_v2_collection_subscriptions
            SET enabled = FALSE, disabled_at = CURRENT_TIMESTAMP
            WHERE instrument_id = ?
            """,
            (int(source.instrument_id),),
        )
        subscription = db.execute(
            "SELECT instrument_id FROM pg_v2_collection_subscriptions WHERE instrument_id = ?",
            (new_instrument_id,),
        ).fetchone()
        if subscription is None:
            db.execute(
                """
                INSERT INTO pg_v2_collection_subscriptions(
                    instrument_id, enabled, resolution, enabled_at, disabled_at
                ) VALUES (?, TRUE, '1m', CURRENT_TIMESTAMP, NULL)
                """,
                (new_instrument_id,),
            )
        else:
            db.execute(
                """
                UPDATE pg_v2_collection_subscriptions
                SET enabled = TRUE, resolution = '1m', enabled_at = CURRENT_TIMESTAMP, disabled_at = NULL
                WHERE instrument_id = ?
                """,
                (new_instrument_id,),
            )

    new_source = resolve_instrument_source_v2(
        provider="saxo",
        provider_instrument_id=str(int(selected.uic)),
        require_subscription=True,
    )
    _persist_event(
        source=source,
        current=_contract_details(configured_client() or _NullClient(), uic=int(source.provider_instrument_id), asset_type=str(source.asset_type)) if False else FuturesContractCandidateV1(
            uic=int(source.provider_instrument_id),
            asset_type=str(source.asset_type),
            symbol=str(source.symbol or ""),
            description=str((source.metadata or {}).get("description") or source.display_name or ""),
            expiry=_utc((source.metadata or {}).get("expiry")),
            primary_listing=None,
            is_tradable=None,
            volume_score=None,
        ),
        selected=selected,
        status="ROLLED",
        selection_method=selection_method,
        effective_at=now,
        new_instrument_id=new_source.instrument_id,
    )
    return new_source


class _NullClient:
    pass


def _persist_roll_event_exact(
    *,
    source: InstrumentSourceV2,
    current: FuturesContractCandidateV1,
    selected: FuturesContractCandidateV1,
    selection_method: str,
    now: datetime,
    new_source: InstrumentSourceV2,
) -> None:
    _persist_event(
        source=source,
        current=current,
        selected=selected,
        status="ROLLED",
        selection_method=selection_method,
        effective_at=now,
        new_instrument_id=new_source.instrument_id,
    )


def _seed_rollover_history_best_effort(
    *,
    client: SaxoClient,
    source: InstrumentSourceV2,
    selected: FuturesContractCandidateV1,
    now: datetime,
    db_path: str,
) -> None:
    try:
        instrument = SaxoInstrument(
            asset=source.market_name,
            uic=selected.uic,
            asset_type=selected.asset_type,
            symbol=selected.symbol,
            description=selected.description,
            expiry=selected.expiry.isoformat() if selected.expiry is not None else None,
            price_multiplier=1.0 if source.price_multiplier is None else float(source.price_multiplier),
        )
        saved = repair_recent_market_history(
            store=RealtimeMarketDataStore(db_path),
            client=client,
            market=source.market_name,
            instrument=instrument,
            now=now,
            lookback_hours=SEED_LOOKBACK_HOURS,
            page_size=SEED_PAGE_SIZE,
            max_pages=SEED_MAX_PAGES,
        )
        LOGGER.info(
            "futures rollover history seeded market=%s uic=%s saved=%d",
            source.market_name,
            selected.uic,
            int(saved),
        )
    except Exception as exc:
        LOGGER.warning(
            "futures rollover history seed failed market=%s uic=%s: %s",
            source.market_name,
            selected.uic,
            exc,
            exc_info=True,
        )


def _due(instrument_id: int, *, mono: float) -> bool:
    previous = _LAST_CHECK_MONO.get(int(instrument_id))
    return previous is None or mono - previous >= CHECK_INTERVAL_SECONDS


def roll_subscribed_futures_once_v1(
    client: SaxoClient | None = None,
    *,
    now: datetime | None = None,
    monotonic_now: float | None = None,
    db_path: str = "pricegauger.db",
) -> FuturesRolloverSummaryV1:
    """Roll monitored expiring Saxo futures to the liquid/front successor safely.

    Collection identity may move forward only when the old exact UIC has no open Saxo
    position and no enabled LIVE_MANAGE controller. Execution authority is never
    migrated by this function. Contract candidates are linked through Saxo's
    PrimaryListing metadata (documented for expiring instruments as the next expiring
    instance), with a bounded exact-AssetType search fallback for already-expired
    legacy sources. Within the final 21 days, recent Saxo chart volume can trigger a
    liquidity-led roll; within two days of expiry the successor is forced even if
    volume is unavailable.
    """
    if not using_postgres():
        return FuturesRolloverSummaryV1(0, 0, 0, 0, 0)
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    current_time = current_time.astimezone(timezone.utc)
    mono = time.monotonic() if monotonic_now is None else float(monotonic_now)
    sources = tuple(
        source
        for source in list_subscribed_sources_v2(provider="saxo")
        if str(source.asset_type or "") in ROLLABLE_ASSET_TYPES
        and _due(source.instrument_id, mono=mono)
    )
    if not sources:
        return FuturesRolloverSummaryV1(0, 0, 0, 0, 0)
    client = client or configured_client()
    if client is None:
        return FuturesRolloverSummaryV1(0, 0, 0, 0, len(sources))

    try:
        observations = tuple(_position_observations_v2(client))
    except Exception as exc:
        LOGGER.warning("futures rollover position guard unavailable: %s", exc, exc_info=True)
        return FuturesRolloverSummaryV1(len(sources), 0, 0, len(sources), 0)

    checked = unchanged = rolled = blocked = failed = 0
    for source in sources:
        _LAST_CHECK_MONO[int(source.instrument_id)] = mono
        checked += 1
        try:
            chain = tuple(_with_volume(client, item) for item in _candidate_chain(client, source=source))
            if not chain:
                unchanged += 1
                continue
            current = chain[0]
            selected, method = select_futures_rollover_candidate_v1(chain, now=current_time)
            if selected.uic == current.uic:
                unchanged += 1
                continue

            block_reason: str | None = None
            if _open_position_exists(observations, uic=current.uic, asset_type=current.asset_type):
                block_reason = "OPEN_SAXO_POSITION"
            elif _live_controller_exists(uic=current.uic, asset_type=current.asset_type):
                block_reason = "ACTIVE_LIVE_CONTROLLER"
            if block_reason:
                _persist_event(
                    source=source,
                    current=current,
                    selected=selected,
                    status="BLOCKED",
                    selection_method=method,
                    effective_at=current_time,
                    new_instrument_id=None,
                    block_reason=block_reason,
                )
                LOGGER.warning(
                    "futures rollover blocked market=%s old=%s new=%s reason=%s",
                    source.market_name,
                    current.uic,
                    selected.uic,
                    block_reason,
                )
                blocked += 1
                continue

            new_source = _switch_collection_source(
                source=source,
                selected=selected,
                now=current_time,
                selection_method=method,
            )
            # Replace the provisional event written by the switch with exact old
            # contract metadata. Event IDs differ, so first remove the provisional
            # row for this exact old/new/time pair if one exists.
            with connect() as db:
                db.execute(
                    """
                    DELETE FROM pg_v2_futures_rollover_events
                    WHERE status='ROLLED' AND market_id=? AND old_uic=? AND new_uic=? AND effective_at=?
                    """,
                    (source.market_id, current.uic, selected.uic, current_time),
                )
            _persist_roll_event_exact(
                source=source,
                current=current,
                selected=selected,
                selection_method=method,
                now=current_time,
                new_source=new_source,
            )
            _seed_rollover_history_best_effort(
                client=client,
                source=new_source,
                selected=selected,
                now=current_time,
                db_path=db_path,
            )
            LOGGER.info(
                "futures rollover completed market=%s old_uic=%s old_symbol=%s new_uic=%s new_symbol=%s method=%s",
                source.market_name,
                current.uic,
                current.symbol,
                selected.uic,
                selected.symbol,
                method,
            )
            rolled += 1
        except Exception as exc:
            failed += 1
            LOGGER.warning(
                "futures rollover check failed market=%s uic=%s: %s",
                source.market_name,
                source.provider_instrument_id,
                exc,
                exc_info=True,
            )
    return FuturesRolloverSummaryV1(checked, unchanged, rolled, blocked, failed)


def load_futures_rollover_events_v1(
    *,
    market: str,
    start: datetime | str | None = None,
    end: datetime | str | None = None,
    limit: int = 50,
) -> tuple[FuturesRolloverEventV1, ...]:
    if not using_postgres():
        return ()
    ensure_futures_rollover_schema_v1()
    clauses = ["market_name = ?", "status = 'ROLLED'"]
    params: list[Any] = [str(market)]
    start_at = _utc(start)
    end_at = _utc(end)
    if start_at is not None:
        clauses.append("effective_at >= ?")
        params.append(start_at)
    if end_at is not None:
        clauses.append("effective_at <= ?")
        params.append(end_at)
    params.append(max(1, min(int(limit), 500)))
    with connect() as db:
        rows = db.execute(
            f"""
            SELECT event_id, market_id, market_name, status, effective_at,
                   old_instrument_id, new_instrument_id, old_uic, new_uic,
                   old_symbol, new_symbol, old_expiry, new_expiry,
                   selection_method, block_reason
            FROM pg_v2_futures_rollover_events
            WHERE {' AND '.join(clauses)}
            ORDER BY effective_at ASC
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()
    result: list[FuturesRolloverEventV1] = []
    for row in rows:
        get = (lambda key, idx: row[key] if isinstance(row, dict) else row[idx])
        effective = _utc(get("effective_at", 4))
        if effective is None:
            continue
        result.append(
            FuturesRolloverEventV1(
                event_id=str(get("event_id", 0)),
                market_id=int(get("market_id", 1)),
                market_name=str(get("market_name", 2)),
                status=str(get("status", 3)),
                effective_at=effective,
                old_instrument_id=int(get("old_instrument_id", 5)),
                new_instrument_id=None if get("new_instrument_id", 6) is None else int(get("new_instrument_id", 6)),
                old_uic=int(get("old_uic", 7)),
                new_uic=None if get("new_uic", 8) is None else int(get("new_uic", 8)),
                old_symbol=str(get("old_symbol", 9) or ""),
                new_symbol=None if get("new_symbol", 10) is None else str(get("new_symbol", 10)),
                old_expiry=_utc(get("old_expiry", 11)),
                new_expiry=_utc(get("new_expiry", 12)),
                selection_method=str(get("selection_method", 13)),
                block_reason=None if get("block_reason", 14) is None else str(get("block_reason", 14)),
            )
        )
    return tuple(result)


__all__ = [
    "FuturesContractCandidateV1",
    "FuturesRolloverEventV1",
    "FuturesRolloverSummaryV1",
    "ROLLABLE_ASSET_TYPES",
    "load_futures_rollover_events_v1",
    "roll_subscribed_futures_once_v1",
    "select_futures_rollover_candidate_v1",
]
