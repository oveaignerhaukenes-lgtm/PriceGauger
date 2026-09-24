from __future__ import annotations

from dataclasses import dataclass
import json

from database import connect
from autotrader_v3_registry_v1 import CONTROL_MODES_V3, MODIFIERS_V3, STRATEGIES_V3, TIMEFRAMES_V3


@dataclass(frozen=True, slots=True)
class AutoTraderConfigV3:
    trader_id: str
    strategy_key: str = "macd"
    timeframe: str = "5m"
    control_mode: str = "Manuell"
    modifiers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.strategy_key not in {x.key for x in STRATEGIES_V3}:
            raise ValueError("unknown V3 strategy")
        if self.timeframe not in TIMEFRAMES_V3:
            raise ValueError("unknown V3 timeframe")
        if self.control_mode not in CONTROL_MODES_V3:
            raise ValueError("unknown V3 control mode")
        unknown = set(self.modifiers) - {x.key for x in MODIFIERS_V3}
        if unknown:
            raise ValueError(f"unknown V3 modifiers: {sorted(unknown)}")


def ensure_autotrader_config_schema_v3(db_path: str = "pricegauger.db") -> None:
    with connect(db_path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS autotrader_v3_config (
          trader_id TEXT PRIMARY KEY,
          strategy_key TEXT NOT NULL,
          timeframe TEXT NOT NULL,
          control_mode TEXT NOT NULL,
          modifiers_json TEXT NOT NULL,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")


def load_autotrader_config_v3(trader_id: str, db_path: str = "pricegauger.db") -> AutoTraderConfigV3:
    ensure_autotrader_config_schema_v3(db_path)
    with connect(db_path) as db:
        row = db.execute(
            "SELECT strategy_key,timeframe,control_mode,modifiers_json FROM autotrader_v3_config WHERE trader_id=?",
            (trader_id,),
        ).fetchone()
    if row is None:
        return AutoTraderConfigV3(trader_id=trader_id)
    get = lambda key, idx: row[key] if isinstance(row, dict) else row[idx]
    return AutoTraderConfigV3(
        trader_id=trader_id,
        strategy_key=str(get("strategy_key", 0)),
        timeframe=str(get("timeframe", 1)),
        control_mode=str(get("control_mode", 2)),
        modifiers=tuple(json.loads(str(get("modifiers_json", 3)) or "[]")),
    )


def save_autotrader_config_v3(config: AutoTraderConfigV3, db_path: str = "pricegauger.db") -> AutoTraderConfigV3:
    ensure_autotrader_config_schema_v3(db_path)
    with connect(db_path) as db:
        db.execute(
            """INSERT INTO autotrader_v3_config(trader_id,strategy_key,timeframe,control_mode,modifiers_json,updated_at)
               VALUES(?,?,?,?,?,CURRENT_TIMESTAMP)
               ON CONFLICT(trader_id) DO UPDATE SET
                 strategy_key=excluded.strategy_key,timeframe=excluded.timeframe,
                 control_mode=excluded.control_mode,modifiers_json=excluded.modifiers_json,
                 updated_at=excluded.updated_at""",
            (config.trader_id, config.strategy_key, config.timeframe, config.control_mode, json.dumps(config.modifiers)),
        )
    return config
