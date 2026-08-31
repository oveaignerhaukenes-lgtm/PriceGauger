from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from database import connect


SIZING_MODE_MAX = "MAX_WITHIN_PILOT"
SIZING_MODE_FIXED = "FIXED_AMOUNT"
SIZING_MODES = {SIZING_MODE_MAX, SIZING_MODE_FIXED}


@dataclass(frozen=True, slots=True)
class EntrySizingPolicyV2:
    account_key: str
    uic: int
    asset_type: str
    direction: str
    sizing_mode: str
    fixed_amount: float | None

    def __post_init__(self) -> None:
        mode = str(self.sizing_mode).strip().upper()
        if mode not in SIZING_MODES:
            raise ValueError(f"unsupported entry sizing mode: {self.sizing_mode}")
        if not str(self.account_key).strip():
            raise ValueError("account_key is required")
        if int(self.uic) <= 0:
            raise ValueError("uic must be positive")
        if not str(self.asset_type).strip():
            raise ValueError("asset_type is required")
        direction = str(self.direction).strip().upper()
        if direction not in {"LONG", "SHORT"}:
            raise ValueError("direction must be LONG or SHORT")
        if mode == SIZING_MODE_FIXED:
            if self.fixed_amount is None or float(self.fixed_amount) <= 0:
                raise ValueError("FIXED_AMOUNT requires a positive fixed_amount")
        elif self.fixed_amount is not None:
            raise ValueError("MAX_WITHIN_PILOT must not persist fixed_amount")


def _row_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row) if not isinstance(row, dict) else row


def load_entry_sizing_policy_v2(
    *,
    account_key: str,
    uic: int,
    asset_type: str,
    direction: str,
) -> EntrySizingPolicyV2:
    normalized_direction = str(direction).strip().upper()
    with connect() as db:
        row = db.execute(
            """
            SELECT account_key, uic, asset_type, direction, sizing_mode, fixed_amount
            FROM pg_v2_autotrader_entry_sizing_policy
            WHERE account_key = ? AND uic = ? AND asset_type = ? AND direction = ?
            """,
            (str(account_key), int(uic), str(asset_type), normalized_direction),
        ).fetchone()
    item = _row_dict(row)
    if item is None:
        return EntrySizingPolicyV2(
            account_key=str(account_key),
            uic=int(uic),
            asset_type=str(asset_type),
            direction=normalized_direction,
            sizing_mode=SIZING_MODE_MAX,
            fixed_amount=None,
        )
    return EntrySizingPolicyV2(
        account_key=str(item["account_key"]),
        uic=int(item["uic"]),
        asset_type=str(item["asset_type"]),
        direction=str(item["direction"]),
        sizing_mode=str(item["sizing_mode"]),
        fixed_amount=None if item["fixed_amount"] is None else float(item["fixed_amount"]),
    )


def save_entry_sizing_policy_v2(
    *,
    account_key: str,
    uic: int,
    asset_type: str,
    direction: str,
    sizing_mode: str,
    fixed_amount: float | None = None,
) -> EntrySizingPolicyV2:
    mode = str(sizing_mode).strip().upper()
    normalized_direction = str(direction).strip().upper()
    policy = EntrySizingPolicyV2(
        account_key=str(account_key),
        uic=int(uic),
        asset_type=str(asset_type),
        direction=normalized_direction,
        sizing_mode=mode,
        fixed_amount=(None if mode == SIZING_MODE_MAX else float(fixed_amount) if fixed_amount is not None else None),
    )
    with connect() as db:
        db.execute(
            """
            INSERT INTO pg_v2_autotrader_entry_sizing_policy(
                account_key, uic, asset_type, direction, sizing_mode, fixed_amount, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, now())
            ON CONFLICT (account_key, uic, asset_type, direction) DO UPDATE SET
                sizing_mode = EXCLUDED.sizing_mode,
                fixed_amount = EXCLUDED.fixed_amount,
                updated_at = now()
            """,
            (
                policy.account_key,
                policy.uic,
                policy.asset_type,
                policy.direction,
                policy.sizing_mode,
                policy.fixed_amount,
            ),
        )
    return policy


__all__ = [
    "EntrySizingPolicyV2",
    "SIZING_MODE_FIXED",
    "SIZING_MODE_MAX",
    "SIZING_MODES",
    "load_entry_sizing_policy_v2",
    "save_entry_sizing_policy_v2",
]
