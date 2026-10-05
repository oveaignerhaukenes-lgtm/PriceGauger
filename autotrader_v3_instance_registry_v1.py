from __future__ import annotations

from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

from autotrader_strategy_enrollment_v2 import load_active_strategy_enrollments_v2
from database import connect


@dataclass(frozen=True, slots=True)
class V3EngineInstanceV1:
    instance_id: str
    account_id: str
    uic: int
    asset_type: str
    market_id: int
    instrument_id: int
    market_name: str
    enabled: bool

    @property
    def pilot_key(self) -> str:
        # V3 config/authority/order state is keyed by the engine instance, never by account.
        return self.instance_id


def ensure_v3_instance_registry_v1(*, db_path: str = "pricegauger.db") -> None:
    with connect(db_path) as db:
        db.execute("""
        CREATE TABLE IF NOT EXISTS autotrader_v3_engine_instances(
          instance_id TEXT PRIMARY KEY,
          account_id TEXT NOT NULL,
          uic INTEGER NOT NULL,
          asset_type TEXT NOT NULL,
          market_id INTEGER NOT NULL,
          instrument_id INTEGER NOT NULL,
          market_name TEXT NOT NULL,
          enabled BOOLEAN NOT NULL DEFAULT TRUE,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(account_id, uic, asset_type)
        )
        """)


def _row(row) -> V3EngineInstanceV1:
    get = lambda key, idx: row[key] if isinstance(row, dict) else row[idx]
    return V3EngineInstanceV1(
        instance_id=str(get("instance_id", 0)), account_id=str(get("account_id", 1)),
        uic=int(get("uic", 2)), asset_type=str(get("asset_type", 3)),
        market_id=int(get("market_id", 4)), instrument_id=int(get("instrument_id", 5)),
        market_name=str(get("market_name", 6)), enabled=bool(get("enabled", 7)),
    )


def load_v3_instances_v1(*, db_path: str = "pricegauger.db") -> tuple[V3EngineInstanceV1, ...]:
    ensure_v3_instance_registry_v1(db_path=db_path)
    with connect(db_path) as db:
        rows = db.execute("""SELECT instance_id,account_id,uic,asset_type,market_id,instrument_id,market_name,enabled
                             FROM autotrader_v3_engine_instances WHERE enabled=TRUE ORDER BY created_at,instance_id""").fetchall()
    return tuple(_row(row) for row in rows)


def create_v3_instance_v1(*, account_id: str, template, db_path: str = "pricegauger.db") -> V3EngineInstanceV1:
    """Create one V3 runtime boundary on a Saxo account using an existing instrument template."""
    ensure_v3_instance_registry_v1(db_path=db_path)
    account = str(account_id or "").strip()
    if not account:
        raise ValueError("V3 instance requires account_id")
    instance_id = str(uuid5(NAMESPACE_URL, f"pricegauger:v3:{account}:{int(template.uic)}:{template.asset_type}"))
    with connect(db_path) as db:
        existing = db.execute("""SELECT instance_id FROM autotrader_v3_engine_instances
                                 WHERE account_id=? AND uic=? AND asset_type=? AND enabled=TRUE""",
                              (account, int(template.uic), str(template.asset_type))).fetchone()
        if existing is not None:
            raise ValueError("This account/instrument already has a V3 instance")
        db.execute("""INSERT INTO autotrader_v3_engine_instances(
                     instance_id,account_id,uic,asset_type,market_id,instrument_id,market_name,enabled)
                     VALUES(?,?,?,?,?,?,?,TRUE)""",
                   (instance_id, account, int(template.uic), str(template.asset_type), int(template.market_id),
                    int(template.instrument_id), str(template.market_name)))
    return next(item for item in load_v3_instances_v1(db_path=db_path) if item.instance_id == instance_id)


def bootstrap_v3_instances_from_enrollments_v1(*, db_path: str = "pricegauger.db") -> tuple[V3EngineInstanceV1, ...]:
    """One-way compatibility bootstrap; never changes an existing V3 instance."""
    ensure_v3_instance_registry_v1(db_path=db_path)
    if load_v3_instances_v1(db_path=db_path):
        return load_v3_instances_v1(db_path=db_path)
    for enrollment in load_active_strategy_enrollments_v2():
        try:
            create_v3_instance_v1(account_id=enrollment.account_id, template=enrollment, db_path=db_path)
        except ValueError:
            pass
    return load_v3_instances_v1(db_path=db_path)
