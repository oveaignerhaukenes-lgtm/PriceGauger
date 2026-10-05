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
        return self.instance_id


def ensure_v3_instance_registry_v1(*, db_path: str = "pricegauger.db") -> None:
    with connect(db_path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS autotrader_v3_engine_instances(
          instance_id TEXT PRIMARY KEY, account_id TEXT NOT NULL, uic INTEGER NOT NULL,
          asset_type TEXT NOT NULL, market_id INTEGER NOT NULL, instrument_id INTEGER NOT NULL,
          market_name TEXT NOT NULL, enabled BOOLEAN NOT NULL DEFAULT TRUE,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(account_id, uic, asset_type))""")


def _row(row) -> V3EngineInstanceV1:
    get=lambda key,idx: row[key] if isinstance(row,dict) else row[idx]
    return V3EngineInstanceV1(str(get("instance_id",0)),str(get("account_id",1)),int(get("uic",2)),
        str(get("asset_type",3)),int(get("market_id",4)),int(get("instrument_id",5)),str(get("market_name",6)),bool(get("enabled",7)))


def load_v3_instances_v1(*, db_path: str = "pricegauger.db") -> tuple[V3EngineInstanceV1, ...]:
    ensure_v3_instance_registry_v1(db_path=db_path)
    with connect(db_path) as db:
        rows=db.execute("""SELECT instance_id,account_id,uic,asset_type,market_id,instrument_id,market_name,enabled
                           FROM autotrader_v3_engine_instances WHERE enabled=TRUE ORDER BY created_at,instance_id""").fetchall()
    return tuple(_row(row) for row in rows)


def create_v3_instance_v1(*, account_id: str, template, db_path: str = "pricegauger.db", instance_id: str | None = None) -> V3EngineInstanceV1:
    ensure_v3_instance_registry_v1(db_path=db_path)
    account=str(account_id or "").strip()
    if not account: raise ValueError("V3 instance requires account_id")
    identity=str(instance_id or uuid5(NAMESPACE_URL,f"pricegauger:v3:{account}:{int(template.uic)}:{template.asset_type}"))
    with connect(db_path) as db:
        existing=db.execute("""SELECT instance_id FROM autotrader_v3_engine_instances
                               WHERE account_id=? AND uic=? AND asset_type=? AND enabled=TRUE""",
                            (account,int(template.uic),str(template.asset_type))).fetchone()
        if existing is not None: raise ValueError("This account/instrument already has a V3 instance")
        db.execute("""INSERT INTO autotrader_v3_engine_instances(
          instance_id,account_id,uic,asset_type,market_id,instrument_id,market_name,enabled)
          VALUES(?,?,?,?,?,?,?,TRUE)""",
          (identity,account,int(template.uic),str(template.asset_type),int(template.market_id),int(template.instrument_id),str(template.market_name)))
    return next(item for item in load_v3_instances_v1(db_path=db_path) if item.instance_id==identity)


def bootstrap_v3_instances_from_enrollments_v1(*, db_path: str = "pricegauger.db") -> tuple[V3EngineInstanceV1, ...]:
    """Migrate existing V3 identity without changing its config, authority or pending state."""
    ensure_v3_instance_registry_v1(db_path=db_path)
    current=load_v3_instances_v1(db_path=db_path)
    if current: return current
    for enrollment in load_active_strategy_enrollments_v2():
        try:
            create_v3_instance_v1(account_id=enrollment.account_id,template=enrollment,
                                  instance_id=enrollment.pilot_key,db_path=db_path)
        except ValueError:
            pass
    return load_v3_instances_v1(db_path=db_path)
