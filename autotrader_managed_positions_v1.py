from __future__ import annotations

from typing import TYPE_CHECKING, Any

from autotrader_schema_v2 import ensure_autotrader_schema_v2
from database import connect

if TYPE_CHECKING:
    from autotrader_risk_control_v2 import PositionObservationV2


def ensure_managed_positions_schema_v1() -> None:
    """Compatibility entrypoint for the centralized AutoTrader v2 schema."""
    ensure_autotrader_schema_v2()


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
    with connect() as db:
        db.execute(
            """
            UPDATE pg_v2_autotrader_managed_positions
            SET managed = FALSE, updated_at = now()
            WHERE account_id = ? AND net_position_id = ?
            """,
            (str(account_id), str(net_position_id)),
        )


def load_active_managed_positions_v1() -> tuple[dict[str, Any], ...]:
    """Return only explicitly active enrollments, without contacting Saxo."""
    with connect() as db:
        rows = db.execute(
            """
            SELECT account_id, net_position_id, uic, asset_type, direction,
                   amount, average_open_price, managed
            FROM pg_v2_autotrader_managed_positions
            WHERE managed = TRUE
            ORDER BY enrolled_at ASC
            """
        ).fetchall()
    records = tuple(_record_dict(row) for row in rows)
    return tuple(record for record in records if record is not None)


def load_managed_position_v1(account_id: str, net_position_id: str) -> dict[str, Any] | None:
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
