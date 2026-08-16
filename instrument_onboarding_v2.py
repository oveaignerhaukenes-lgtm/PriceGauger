from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from database import connect


@dataclass(frozen=True, slots=True)
class SaxoInstrumentOnboardingRequestV2:
    market_name: str
    market_category: str
    display_name: str
    uic: int
    asset_type: str
    symbol: str | None = None
    price_multiplier: float = 1.0
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class InstrumentOnboardingResultV2:
    market_id: int
    instrument_id: int
    instrument_source_id: int
    market_name: str
    market_category: str
    display_name: str
    provider: str
    provider_instrument_id: str
    asset_type: str
    subscription_enabled: bool
    reused_existing_source: bool


def _row_value(row, key: str, index: int):
    if isinstance(row, dict):
        return row[key]
    try:
        return row[key]
    except (TypeError, IndexError):
        return row[index]


def _normalize_required(value: str, *, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    return normalized


def _enable_subscription(db, *, instrument_id: int) -> None:
    row = db.execute(
        "SELECT instrument_id FROM pg_v2_collection_subscriptions WHERE instrument_id = ?",
        (int(instrument_id),),
    ).fetchone()
    if row is None:
        db.execute(
            """
            INSERT INTO pg_v2_collection_subscriptions
                (instrument_id, enabled, resolution, enabled_at, disabled_at)
            VALUES (?, TRUE, '1m', CURRENT_TIMESTAMP, NULL)
            """,
            (int(instrument_id),),
        )
        return
    db.execute(
        """
        UPDATE pg_v2_collection_subscriptions
        SET enabled = TRUE,
            resolution = '1m',
            enabled_at = CURRENT_TIMESTAMP,
            disabled_at = NULL
        WHERE instrument_id = ?
        """,
        (int(instrument_id),),
    )


def onboard_saxo_instrument_v2(
    request: SaxoInstrumentOnboardingRequestV2,
) -> InstrumentOnboardingResultV2:
    """Atomically register one explicitly selected Saxo instrument and subscribe it.

    The Saxo catalogue remains external/read-only. This function is the bounded
    transition into PriceGauger's canonical v2 registry. Existing provider
    identities are reused rather than remapped to a different canonical market.
    Every newly-created registry row and the 1m subscription commit together or
    roll back together.
    """
    market_name = _normalize_required(request.market_name, field="market_name")
    market_category = _normalize_required(request.market_category, field="market_category").lower()
    display_name = _normalize_required(request.display_name, field="display_name")
    asset_type = _normalize_required(request.asset_type, field="asset_type")
    if int(request.uic) <= 0:
        raise ValueError("uic must be positive")
    if float(request.price_multiplier) <= 0:
        raise ValueError("price_multiplier must be positive")

    provider = "saxo"
    source_id = str(int(request.uic))
    metadata_json = json.dumps(request.metadata or {}, sort_keys=True, separators=(",", ":"))

    with connect() as db:
        existing = db.execute(
            """
            SELECT s.instrument_source_id, s.instrument_id, s.asset_type,
                   i.display_name, m.market_id, m.name, m.category
            FROM pg_v2_instrument_sources s
            JOIN pg_v2_instruments i ON i.instrument_id = s.instrument_id AND i.active = TRUE
            JOIN pg_v2_markets m ON m.market_id = i.market_id AND m.active = TRUE
            WHERE s.provider = ? AND s.provider_instrument_id = ? AND s.active = TRUE
            ORDER BY s.instrument_source_id DESC
            LIMIT 1
            """,
            (provider, source_id),
        ).fetchone()
        if existing is not None:
            existing_asset_type = str(_row_value(existing, "asset_type", 2) or "")
            if existing_asset_type and existing_asset_type != asset_type:
                raise ValueError(
                    "existing Saxo provider identity has a different AssetType; refusing ambiguous remap"
                )
            instrument_id = int(_row_value(existing, "instrument_id", 1))
            _enable_subscription(db, instrument_id=instrument_id)
            return InstrumentOnboardingResultV2(
                market_id=int(_row_value(existing, "market_id", 4)),
                instrument_id=instrument_id,
                instrument_source_id=int(_row_value(existing, "instrument_source_id", 0)),
                market_name=str(_row_value(existing, "name", 5)),
                market_category=str(_row_value(existing, "category", 6)),
                display_name=str(_row_value(existing, "display_name", 3)),
                provider=provider,
                provider_instrument_id=source_id,
                asset_type=asset_type,
                subscription_enabled=True,
                reused_existing_source=True,
            )

        market = db.execute(
            "SELECT market_id, category FROM pg_v2_markets WHERE name = ? AND active = TRUE",
            (market_name,),
        ).fetchone()
        if market is None:
            db.execute(
                """
                INSERT INTO pg_v2_markets (name, category, active)
                VALUES (?, ?, TRUE)
                """,
                (market_name, market_category),
            )
            market = db.execute(
                "SELECT market_id, category FROM pg_v2_markets WHERE name = ? AND active = TRUE",
                (market_name,),
            ).fetchone()
        elif str(_row_value(market, "category", 1)).lower() != market_category:
            raise ValueError(
                f"market {market_name!r} already exists with category "
                f"{_row_value(market, 'category', 1)!r}; refusing silent semantic change"
            )
        market_id = int(_row_value(market, "market_id", 0))

        instrument = db.execute(
            """
            SELECT instrument_id
            FROM pg_v2_instruments
            WHERE market_id = ? AND instrument_type = ? AND display_name = ? AND active = TRUE
            ORDER BY instrument_id ASC
            LIMIT 1
            """,
            (market_id, asset_type, display_name),
        ).fetchone()
        if instrument is None:
            db.execute(
                """
                INSERT INTO pg_v2_instruments
                    (market_id, instrument_type, display_name, active)
                VALUES (?, ?, ?, TRUE)
                """,
                (market_id, asset_type, display_name),
            )
            instrument = db.execute(
                """
                SELECT instrument_id
                FROM pg_v2_instruments
                WHERE market_id = ? AND instrument_type = ? AND display_name = ? AND active = TRUE
                ORDER BY instrument_id DESC
                LIMIT 1
                """,
                (market_id, asset_type, display_name),
            ).fetchone()
        instrument_id = int(_row_value(instrument, "instrument_id", 0))

        json_placeholder = "?::jsonb" if db.is_postgres else "?"
        db.execute(
            f"""
            INSERT INTO pg_v2_instrument_sources
                (instrument_id, provider, provider_instrument_id, asset_type, symbol,
                 price_multiplier, metadata_json, active)
            VALUES (?, ?, ?, ?, ?, ?, {json_placeholder}, TRUE)
            """,
            (
                instrument_id,
                provider,
                source_id,
                asset_type,
                (request.symbol or "").strip() or None,
                float(request.price_multiplier),
                metadata_json,
            ),
        )
        source = db.execute(
            """
            SELECT instrument_source_id
            FROM pg_v2_instrument_sources
            WHERE instrument_id = ? AND provider = ? AND provider_instrument_id = ? AND active = TRUE
            ORDER BY instrument_source_id DESC
            LIMIT 1
            """,
            (instrument_id, provider, source_id),
        ).fetchone()
        instrument_source_id = int(_row_value(source, "instrument_source_id", 0))

        _enable_subscription(db, instrument_id=instrument_id)

        return InstrumentOnboardingResultV2(
            market_id=market_id,
            instrument_id=instrument_id,
            instrument_source_id=instrument_source_id,
            market_name=market_name,
            market_category=market_category,
            display_name=display_name,
            provider=provider,
            provider_instrument_id=source_id,
            asset_type=asset_type,
            subscription_enabled=True,
            reused_existing_source=False,
        )
