from __future__ import annotations

from typing import Any

from autotrader_risk_dry_run_v2 import PositionObservationV2
from database import connect, using_postgres


def ensure_managed_positions_schema_v1() -> None:
    if not using_postgres():
        raise RuntimeError("Auto-manage position enrollment requires PostgreSQL")
    with connect() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS pg_v2_autotrader_managed_positions (
                account_id TEXT NOT NULL,
                net_position_id TEXT NOT NULL,
                uic BIGINT NOT NULL,
                asset_type TEXT NOT NULL,
                direction TEXT NOT NULL,
                amount DOUBLE PRECISION NOT NULL,
                average_open_price DOUBLE PRECISION NOT NULL,
                managed BOOLEAN NOT NULL DEFAULT TRUE,
                enrolled_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY(account_id, net_position_id)
            )
            """
        )


def _record_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    try:
        return dict(row)
    except Exception:
        return {
            "account_id": row[0],
            "net_position_id": row[1],
            "uic": row[2],
            "asset_type": row[3],
            "direction": row[4],
            "amount": row[5],
            "average_open_price": row[6],
            "managed": row[7],
        }


def managed_position_matches_v1(record: dict[str, Any], observation: PositionObservationV2) -> bool:
    """Require the enrolled position identity to still be exactly the position we see now.

    This prevents a new/reopened/resized position from inheriting Auto-manage merely
    because Saxo later presents the same net-position id.
    """
    if not bool(record.get("managed")):
        return False
    if str(record.get("account_id") or "") != observation.account_id:
        return False
    if str(record.get("net_position_id") or "") != observation.net_position_id:
        return False
    if int(record.get("uic") or -1) != int(observation.uic):
        return False
    if str(record.get("asset_type") or "") != observation.asset_type:
        return False
    if str(record.get("direction") or "").strip().lower() != observation.direction.strip().lower():
        return False
    if abs(float(record.get("amount") or 0.0) - float(observation.amount)) > 1e-12:
        return False
    if abs(float(record.get("average_open_price") or 0.0) - float(observation.average_open_price)) > 1e-12:
        return False
    return True


def enroll_position_v1(observation: PositionObservationV2) -> None:
    """Explicitly opt one currently observed Saxo position into Auto-manage."""
    ensure_managed_positions_schema_v1()
    with connect() as db:
        db.execute(
            """
            INSERT INTO pg_v2_autotrader_managed_positions
                (account_id, net_position_id, uic, asset_type, direction,
                 amount, average_open_price, managed, enrolled_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, TRUE, now(), now())
            ON CONFLICT (account_id, net_position_id) DO UPDATE SET
                uic = EXCLUDED.uic,
                asset_type = EXCLUDED.asset_type,
                direction = EXCLUDED.direction,
                amount = EXCLUDED.amount,
                average_open_price = EXCLUDED.average_open_price,
                managed = TRUE,
                enrolled_at = now(),
                updated_at = now()
            """,
            (
                observation.account_id,
                observation.net_position_id,
                int(observation.uic),
                observation.asset_type,
                observation.direction,
                float(observation.amount),
                float(observation.average_open_price),
            ),
        )


def stop_managing_position_v1(account_id: str, net_position_id: str) -> None:
    ensure_managed_positions_schema_v1()
    with connect() as db:
        db.execute(
            """
            UPDATE pg_v2_autotrader_managed_positions
            SET managed = FALSE, updated_at = now()
            WHERE account_id = ? AND net_position_id = ?
            """,
            (str(account_id), str(net_position_id)),
        )


def load_managed_position_v1(account_id: str, net_position_id: str) -> dict[str, Any] | None:
    ensure_managed_positions_schema_v1()
    with connect() as db:
        row = db.execute(
            """
            SELECT account_id, net_position_id, uic, asset_type, direction,
                   amount, average_open_price, managed
            FROM pg_v2_autotrader_managed_positions
            WHERE account_id = ? AND net_position_id = ?
            """,
            (str(account_id), str(net_position_id)),
        ).fetchone()
    return _record_dict(row)


def is_position_managed_v1(observation: PositionObservationV2) -> bool:
    record = load_managed_position_v1(observation.account_id, observation.net_position_id)
    return bool(record and managed_position_matches_v1(record, observation))
