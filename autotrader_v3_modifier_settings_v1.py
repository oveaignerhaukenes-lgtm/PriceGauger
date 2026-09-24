from __future__ import annotations

from dataclasses import dataclass, asdict
import json
from typing import Any

from database import connect


DEFAULTS_V3: dict[str, dict[str, Any]] = {
    "impulse": {"sensitivity": 1.0, "max_boost": 1.5},
    "reversal": {"confirmation_bars": 2, "strength": 1.0},
    "take-profit": {"giveback_pct": 10.0, "min_peak_profit_pct": 0.20, "reentry_cooldown_seconds": 30},
    "whipsaw": {"lookback_bars": 12, "max_direction_changes": 4, "cooldown_bars": 3},
    "regime": {"lookback_bars": 30, "trend_threshold": 0.60},
}


def ensure_modifier_settings_schema_v3(db_path: str = "pricegauger.db") -> None:
    with connect(db_path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS autotrader_v3_modifier_settings (
          trader_id TEXT NOT NULL,
          modifier_key TEXT NOT NULL,
          settings_json TEXT NOT NULL,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY(trader_id, modifier_key)
        )""")


def load_modifier_settings_v3(trader_id: str, modifier_key: str, db_path: str = "pricegauger.db") -> dict[str, Any]:
    if modifier_key not in DEFAULTS_V3:
        raise ValueError(f"unknown V3 modifier: {modifier_key}")
    ensure_modifier_settings_schema_v3(db_path)
    with connect(db_path) as db:
        row = db.execute(
            "SELECT settings_json FROM autotrader_v3_modifier_settings WHERE trader_id=? AND modifier_key=?",
            (trader_id, modifier_key),
        ).fetchone()
    defaults = dict(DEFAULTS_V3[modifier_key])
    if row is None:
        return defaults
    raw = row["settings_json"] if isinstance(row, dict) else row[0]
    loaded = json.loads(str(raw) or "{}")
    defaults.update({key: value for key, value in loaded.items() if key in defaults})
    return defaults


def save_modifier_settings_v3(trader_id: str, modifier_key: str, settings: dict[str, Any], db_path: str = "pricegauger.db") -> dict[str, Any]:
    if modifier_key not in DEFAULTS_V3:
        raise ValueError(f"unknown V3 modifier: {modifier_key}")
    allowed = set(DEFAULTS_V3[modifier_key])
    unknown = set(settings) - allowed
    if unknown:
        raise ValueError(f"unknown settings for {modifier_key}: {sorted(unknown)}")
    merged = dict(DEFAULTS_V3[modifier_key])
    merged.update(settings)
    ensure_modifier_settings_schema_v3(db_path)
    with connect(db_path) as db:
        db.execute(
            """INSERT INTO autotrader_v3_modifier_settings(trader_id,modifier_key,settings_json,updated_at)
               VALUES(?,?,?,CURRENT_TIMESTAMP)
               ON CONFLICT(trader_id,modifier_key) DO UPDATE SET
                 settings_json=excluded.settings_json,updated_at=excluded.updated_at""",
            (trader_id, modifier_key, json.dumps(merged, sort_keys=True)),
        )
    return merged
