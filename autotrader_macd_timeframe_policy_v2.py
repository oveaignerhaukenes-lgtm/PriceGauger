from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from database import connect


DEFAULT_MACD_TIMEFRAME_MINUTES = 30
SUPPORTED_MACD_TIMEFRAME_MINUTES = (5, 15, 30)


@dataclass(frozen=True, slots=True)
class MacdTimeframePolicyV2:
    account_id: str
    uic: int
    asset_type: str
    timeframe_minutes: int

    def __post_init__(self) -> None:
        if not str(self.account_id).strip():
            raise ValueError("account_id is required")
        if int(self.uic) <= 0:
            raise ValueError("uic must be positive")
        if not str(self.asset_type).strip():
            raise ValueError("asset_type is required")
        if int(self.timeframe_minutes) not in SUPPORTED_MACD_TIMEFRAME_MINUTES:
            raise ValueError("MACD timeframe must be 5, 15 or 30 minutes")


def _row_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row) if not isinstance(row, dict) else row


def load_macd_timeframe_policy_v2(
    *,
    account_id: str,
    uic: int,
    asset_type: str,
) -> MacdTimeframePolicyV2:
    with connect() as db:
        row = db.execute(
            """
            SELECT account_id, uic, asset_type, timeframe_minutes
            FROM pg_v2_autotrader_macd_timeframe_policy
            WHERE account_id = ? AND uic = ? AND asset_type = ?
            """,
            (str(account_id), int(uic), str(asset_type)),
        ).fetchone()
    item = _row_dict(row)
    if item is None:
        return MacdTimeframePolicyV2(
            account_id=str(account_id),
            uic=int(uic),
            asset_type=str(asset_type),
            timeframe_minutes=DEFAULT_MACD_TIMEFRAME_MINUTES,
        )
    return MacdTimeframePolicyV2(
        account_id=str(item["account_id"]),
        uic=int(item["uic"]),
        asset_type=str(item["asset_type"]),
        timeframe_minutes=int(item["timeframe_minutes"]),
    )


def save_macd_timeframe_policy_v2(
    *,
    account_id: str,
    uic: int,
    asset_type: str,
    timeframe_minutes: int,
) -> MacdTimeframePolicyV2:
    requested = MacdTimeframePolicyV2(
        account_id=str(account_id),
        uic=int(uic),
        asset_type=str(asset_type),
        timeframe_minutes=int(timeframe_minutes),
    )
    with connect() as db:
        existing = db.execute(
            """
            SELECT timeframe_minutes
            FROM pg_v2_autotrader_macd_timeframe_policy
            WHERE account_id = ? AND uic = ? AND asset_type = ?
            """,
            (requested.account_id, requested.uic, requested.asset_type),
        ).fetchone()
        existing_value = None
        if existing is not None:
            if isinstance(existing, dict):
                existing_value = int(existing["timeframe_minutes"])
            else:
                existing_value = int(existing[0])
        if existing_value is not None and existing_value == requested.timeframe_minutes:
            return requested

        active = db.execute(
            """
            SELECT 1
            FROM pg_v2_autotrader_strategy_enrollments
            WHERE enabled = TRUE AND account_id = ? AND uic = ? AND asset_type = ?
            LIMIT 1
            """,
            (requested.account_id, requested.uic, requested.asset_type),
        ).fetchone()
        if active is not None:
            raise ValueError("stop active AutoManager pilots before changing MACD timeframe")

        db.execute(
            """
            INSERT INTO pg_v2_autotrader_macd_timeframe_policy(
                account_id, uic, asset_type, timeframe_minutes, updated_at
            ) VALUES (?, ?, ?, ?, now())
            ON CONFLICT (account_id, uic, asset_type) DO UPDATE SET
                timeframe_minutes = EXCLUDED.timeframe_minutes,
                updated_at = now()
            """,
            (
                requested.account_id,
                requested.uic,
                requested.asset_type,
                requested.timeframe_minutes,
            ),
        )
    return requested


__all__ = [
    "DEFAULT_MACD_TIMEFRAME_MINUTES",
    "MacdTimeframePolicyV2",
    "SUPPORTED_MACD_TIMEFRAME_MINUTES",
    "load_macd_timeframe_policy_v2",
    "save_macd_timeframe_policy_v2",
]
