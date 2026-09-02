from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping

from database import connect


UI_WORKSPACE_STATE_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class UiWorkspaceStateV2:
    page_key: str
    schema_version: int
    state: dict[str, Any]


def ensure_ui_workspace_state_schema_v2() -> None:
    """Create the read-model-only UI preference store when needed.

    This table is deliberately separate from every execution/risk authority table.
    Restoring a UI workspace therefore cannot arm trading, approve an order, enable
    a strategy enrollment or otherwise create execution authority.
    """
    with connect() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS pg_v2_ui_workspace_state (
                page_key TEXT PRIMARY KEY,
                schema_version INTEGER NOT NULL,
                state_json TEXT NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def load_ui_workspace_state_v2(
    page_key: str,
    *,
    schema_version: int = UI_WORKSPACE_STATE_SCHEMA_VERSION,
) -> UiWorkspaceStateV2 | None:
    key = str(page_key).strip()
    if not key:
        raise ValueError("page_key is required")
    ensure_ui_workspace_state_schema_v2()
    with connect() as db:
        row = db.execute(
            """
            SELECT page_key, schema_version, state_json
            FROM pg_v2_ui_workspace_state
            WHERE page_key = ?
            """,
            (key,),
        ).fetchone()
    if row is None:
        return None
    item = dict(row) if not isinstance(row, dict) else row
    stored_version = int(item["schema_version"])
    if stored_version != int(schema_version):
        return None
    try:
        value = json.loads(str(item["state_json"]))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    return UiWorkspaceStateV2(
        page_key=str(item["page_key"]),
        schema_version=stored_version,
        state=dict(value),
    )


def save_ui_workspace_state_v2(
    page_key: str,
    state: Mapping[str, Any],
    *,
    schema_version: int = UI_WORKSPACE_STATE_SCHEMA_VERSION,
) -> UiWorkspaceStateV2:
    key = str(page_key).strip()
    if not key:
        raise ValueError("page_key is required")
    version = int(schema_version)
    if version <= 0:
        raise ValueError("schema_version must be positive")
    payload = dict(state)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    ensure_ui_workspace_state_schema_v2()
    with connect() as db:
        db.execute(
            """
            INSERT INTO pg_v2_ui_workspace_state(page_key, schema_version, state_json, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT (page_key) DO UPDATE SET
                schema_version = EXCLUDED.schema_version,
                state_json = EXCLUDED.state_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (key, version, encoded),
        )
    return UiWorkspaceStateV2(page_key=key, schema_version=version, state=payload)


__all__ = [
    "UI_WORKSPACE_STATE_SCHEMA_VERSION",
    "UiWorkspaceStateV2",
    "ensure_ui_workspace_state_schema_v2",
    "load_ui_workspace_state_v2",
    "save_ui_workspace_state_v2",
]
