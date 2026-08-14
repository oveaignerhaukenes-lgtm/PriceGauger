from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any

from database import connect


@dataclass(frozen=True, slots=True)
class InstrumentSourceV2:
    market_id: int
    market_name: str
    instrument_id: int
    instrument_type: str
    display_name: str
    provider: str
    provider_instrument_id: str
    asset_type: str | None = None
    symbol: str | None = None
    price_multiplier: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def provider_key(self) -> tuple[str, str]:
        return self.provider, self.provider_instrument_id


def _row_value(row, key: str, index: int):
    if isinstance(row, dict):
        return row[key]
    try:
        return row[key]
    except (TypeError, IndexError):
        return row[index]


def _json_placeholder(db) -> str:
    return "?::jsonb" if db.is_postgres else "?"


def _json_object(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, str):
        return dict(json.loads(value) or {})
    return dict(value)


def ensure_market_v2(
    *,
    name: str,
    category: str,
    base_currency: str | None = None,
    quote_currency: str | None = None,
    canonical_unit: str | None = None,
) -> int:
    normalized = name.strip()
    if not normalized:
        raise ValueError("market name is required")
    with connect() as db:
        row = db.execute(
            "SELECT market_id FROM pg_v2_markets WHERE name = ?",
            (normalized,),
        ).fetchone()
        if row is None:
            db.execute(
                """
                INSERT INTO pg_v2_markets
                    (name, category, base_currency, quote_currency, canonical_unit, active)
                VALUES (?, ?, ?, ?, ?, TRUE)
                """,
                (normalized, category, base_currency, quote_currency, canonical_unit),
            )
            row = db.execute(
                "SELECT market_id FROM pg_v2_markets WHERE name = ?",
                (normalized,),
            ).fetchone()
        return int(_row_value(row, "market_id", 0))


def ensure_instrument_v2(
    *,
    market_id: int,
    instrument_type: str,
    display_name: str,
) -> int:
    label = display_name.strip()
    if not label:
        raise ValueError("instrument display_name is required")
    with connect() as db:
        row = db.execute(
            """
            SELECT instrument_id
            FROM pg_v2_instruments
            WHERE market_id = ? AND instrument_type = ? AND display_name = ? AND active = TRUE
            ORDER BY instrument_id ASC
            LIMIT 1
            """,
            (int(market_id), instrument_type, label),
        ).fetchone()
        if row is None:
            db.execute(
                """
                INSERT INTO pg_v2_instruments
                    (market_id, instrument_type, display_name, active)
                VALUES (?, ?, ?, TRUE)
                """,
                (int(market_id), instrument_type, label),
            )
            row = db.execute(
                """
                SELECT instrument_id
                FROM pg_v2_instruments
                WHERE market_id = ? AND instrument_type = ? AND display_name = ? AND active = TRUE
                ORDER BY instrument_id DESC
                LIMIT 1
                """,
                (int(market_id), instrument_type, label),
            ).fetchone()
        return int(_row_value(row, "instrument_id", 0))


def ensure_instrument_source_v2(
    *,
    instrument_id: int,
    provider: str,
    provider_instrument_id: str | int,
    asset_type: str | None = None,
    symbol: str | None = None,
    price_multiplier: float | None = None,
    metadata: dict[str, Any] | None = None,
) -> int:
    provider_name = provider.strip().lower()
    source_id = str(provider_instrument_id).strip()
    if not provider_name or not source_id:
        raise ValueError("provider and provider_instrument_id are required")
    metadata_json = json.dumps(metadata or {}, sort_keys=True, separators=(",", ":"))
    with connect() as db:
        row = db.execute(
            """
            SELECT instrument_source_id
            FROM pg_v2_instrument_sources
            WHERE instrument_id = ? AND provider = ? AND provider_instrument_id = ? AND active = TRUE
            ORDER BY instrument_source_id DESC
            LIMIT 1
            """,
            (int(instrument_id), provider_name, source_id),
        ).fetchone()
        if row is None:
            json_value = _json_placeholder(db)
            db.execute(
                f"""
                INSERT INTO pg_v2_instrument_sources
                    (instrument_id, provider, provider_instrument_id, asset_type, symbol,
                     price_multiplier, metadata_json, active)
                VALUES (?, ?, ?, ?, ?, ?, {json_value}, TRUE)
                """,
                (
                    int(instrument_id), provider_name, source_id, asset_type, symbol,
                    price_multiplier, metadata_json,
                ),
            )
            row = db.execute(
                """
                SELECT instrument_source_id
                FROM pg_v2_instrument_sources
                WHERE instrument_id = ? AND provider = ? AND provider_instrument_id = ? AND active = TRUE
                ORDER BY instrument_source_id DESC
                LIMIT 1
                """,
                (int(instrument_id), provider_name, source_id),
            ).fetchone()
        return int(_row_value(row, "instrument_source_id", 0))


def set_collection_subscription_v2(*, instrument_id: int, enabled: bool) -> None:
    with connect() as db:
        existing = db.execute(
            "SELECT instrument_id FROM pg_v2_collection_subscriptions WHERE instrument_id = ?",
            (int(instrument_id),),
        ).fetchone()
        if existing is None:
            db.execute(
                """
                INSERT INTO pg_v2_collection_subscriptions
                    (instrument_id, enabled, resolution, enabled_at, disabled_at)
                VALUES (?, ?, '1m', CURRENT_TIMESTAMP, NULL)
                """,
                (int(instrument_id), bool(enabled)),
            )
        else:
            db.execute(
                """
                UPDATE pg_v2_collection_subscriptions
                SET enabled = ?,
                    enabled_at = CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE enabled_at END,
                    disabled_at = CASE WHEN ? THEN NULL ELSE CURRENT_TIMESTAMP END
                WHERE instrument_id = ?
                """,
                (bool(enabled), bool(enabled), bool(enabled), int(instrument_id)),
            )


def resolve_instrument_source_v2(
    *,
    provider: str,
    provider_instrument_id: str | int,
    require_subscription: bool = False,
) -> InstrumentSourceV2:
    provider_name = provider.strip().lower()
    source_id = str(provider_instrument_id).strip()
    subscription_join = (
        "JOIN pg_v2_collection_subscriptions c ON c.instrument_id = i.instrument_id AND c.enabled = TRUE"
        if require_subscription else ""
    )
    with connect() as db:
        row = db.execute(
            f"""
            SELECT m.market_id, m.name, i.instrument_id, i.instrument_type, i.display_name,
                   s.provider, s.provider_instrument_id, s.asset_type, s.symbol,
                   s.price_multiplier, s.metadata_json
            FROM pg_v2_instrument_sources s
            JOIN pg_v2_instruments i ON i.instrument_id = s.instrument_id AND i.active = TRUE
            JOIN pg_v2_markets m ON m.market_id = i.market_id AND m.active = TRUE
            {subscription_join}
            WHERE s.provider = ? AND s.provider_instrument_id = ? AND s.active = TRUE
            ORDER BY s.instrument_source_id DESC
            LIMIT 1
            """,
            (provider_name, source_id),
        ).fetchone()
    if row is None:
        raise LookupError(f"no active v2 instrument source for {provider_name}:{source_id}")
    multiplier = _row_value(row, "price_multiplier", 9)
    return InstrumentSourceV2(
        market_id=int(_row_value(row, "market_id", 0)),
        market_name=str(_row_value(row, "name", 1)),
        instrument_id=int(_row_value(row, "instrument_id", 2)),
        instrument_type=str(_row_value(row, "instrument_type", 3)),
        display_name=str(_row_value(row, "display_name", 4)),
        provider=str(_row_value(row, "provider", 5)),
        provider_instrument_id=str(_row_value(row, "provider_instrument_id", 6)),
        asset_type=_row_value(row, "asset_type", 7),
        symbol=_row_value(row, "symbol", 8),
        price_multiplier=float(multiplier) if multiplier is not None else None,
        metadata=_json_object(_row_value(row, "metadata_json", 10)),
    )


def list_subscribed_sources_v2(*, provider: str | None = None) -> tuple[InstrumentSourceV2, ...]:
    parameters: tuple[Any, ...] = ()
    provider_filter = ""
    if provider is not None:
        provider_filter = "AND s.provider = ?"
        parameters = (provider.strip().lower(),)
    with connect() as db:
        rows = db.execute(
            f"""
            SELECT s.provider, s.provider_instrument_id
            FROM pg_v2_instrument_sources s
            JOIN pg_v2_collection_subscriptions c
              ON c.instrument_id = s.instrument_id AND c.enabled = TRUE
            JOIN pg_v2_instruments i ON i.instrument_id = s.instrument_id AND i.active = TRUE
            JOIN pg_v2_markets m ON m.market_id = i.market_id AND m.active = TRUE
            WHERE s.active = TRUE {provider_filter}
            ORDER BY m.name, i.display_name, s.provider, s.provider_instrument_id
            """,
            parameters,
        ).fetchall()
    return tuple(
        resolve_instrument_source_v2(
            provider=str(_row_value(row, "provider", 0)),
            provider_instrument_id=str(_row_value(row, "provider_instrument_id", 1)),
            require_subscription=True,
        )
        for row in rows
    )
