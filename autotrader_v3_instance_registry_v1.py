from __future__ import annotations
from dataclasses import dataclass
from uuid import NAMESPACE_URL,uuid5

from autotrader_engine_identity_v1 import ENGINE_V2,ENGINE_V3,enrollment_engine_v1
from autotrader_strategy_enrollment_v2 import load_active_strategy_enrollments_v2
from database import connect,using_postgres

_LEGACY_REGISTRY_MIGRATION_V1="2026-10-06-filter-v2-preserve-v3-identity-v1"


@dataclass(frozen=True,slots=True)
class V3EngineInstanceV1:
    instance_id:str;account_id:str;uic:int;asset_type:str;market_id:int;instrument_id:int;market_name:str;enabled:bool
    @property
    def pilot_key(self)->str:return self.instance_id


def ensure_v3_instance_registry_v1(*,db_path='pricegauger.db')->None:
    with connect(db_path) as db:
        db.execute('''CREATE TABLE IF NOT EXISTS autotrader_v3_engine_instances(
          instance_id TEXT PRIMARY KEY,account_id TEXT NOT NULL,uic INTEGER NOT NULL,
          asset_type TEXT NOT NULL,market_id INTEGER NOT NULL,instrument_id INTEGER NOT NULL,
          market_name TEXT NOT NULL,enabled BOOLEAN NOT NULL DEFAULT TRUE,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(account_id,uic,asset_type))''')
        db.execute('''CREATE UNIQUE INDEX IF NOT EXISTS uq_v3_enabled_account
          ON autotrader_v3_engine_instances(account_id) WHERE enabled=TRUE''')
        db.execute('''CREATE TABLE IF NOT EXISTS autotrader_v3_registry_migrations(
          migration_key TEXT PRIMARY KEY,completed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')


def _row(row):
    g=lambda k,n:row[k] if isinstance(row,dict) else row[n]
    return V3EngineInstanceV1(str(g('instance_id',0)),str(g('account_id',1)),int(g('uic',2)),str(g('asset_type',3)),int(g('market_id',4)),int(g('instrument_id',5)),str(g('market_name',6)),bool(g('enabled',7)))


def load_v3_instances_v1(*,db_path='pricegauger.db'):
    ensure_v3_instance_registry_v1(db_path=db_path)
    with connect(db_path) as db:
        rows=db.execute('''SELECT instance_id,account_id,uic,asset_type,market_id,instrument_id,market_name,enabled
          FROM autotrader_v3_engine_instances WHERE enabled=TRUE ORDER BY created_at,instance_id''').fetchall()
    return tuple(_row(r) for r in rows)


def create_v3_instance_v1(*,account_id:str,template,db_path='pricegauger.db',instance_id=None):
    ensure_v3_instance_registry_v1(db_path=db_path);account=str(account_id or '').strip()
    if not account:raise ValueError('V3 instance requires account_id')
    identity=str(instance_id or uuid5(NAMESPACE_URL,f'pricegauger:v3:{account}:{int(template.uic)}:{template.asset_type}'))
    with connect(db_path) as db:
        existing=db.execute('SELECT instance_id FROM autotrader_v3_engine_instances WHERE account_id=? AND enabled=TRUE',(account,)).fetchone()
        if existing is not None:raise ValueError('This Saxo account is already attached to a V3 instance')
        db.execute('''INSERT INTO autotrader_v3_engine_instances(instance_id,account_id,uic,asset_type,market_id,instrument_id,market_name,enabled)
          VALUES(?,?,?,?,?,?,?,TRUE)''',(identity,account,int(template.uic),str(template.asset_type),int(template.market_id),int(template.instrument_id),str(template.market_name)))
    return next(i for i in load_v3_instances_v1(db_path=db_path) if i.instance_id==identity)


def _legacy_registry_migration_complete_v1(*,db_path='pricegauger.db')->bool:
    ensure_v3_instance_registry_v1(db_path=db_path)
    with connect(db_path) as db:
        row=db.execute('SELECT migration_key FROM autotrader_v3_registry_migrations WHERE migration_key=?',
            (_LEGACY_REGISTRY_MIGRATION_V1,)).fetchone()
    return row is not None


def _migrate_legacy_registry_rows_v1(enrollments,*,db_path='pricegauger.db')->None:
    """Repair the one-time registry seed without changing V2 enrollment/control state.

    The first registry bootstrap copied every active legacy enrollment, including V2
    pilots.  Only legacy enrollments whose strategy identity belongs to ENGINE_V3 are
    valid V3 instance identities.  Exact V2-pilot registry rows are therefore safe to
    remove; an unrelated row already occupying a V3 account is an ambiguity and fails
    closed rather than being replaced.
    """
    ensure_v3_instance_registry_v1(db_path=db_path)
    v2=tuple(e for e in enrollments if enrollment_engine_v1(e)==ENGINE_V2)
    v3=tuple(e for e in enrollments if enrollment_engine_v1(e)==ENGINE_V3)
    with connect(db_path) as db:
        marker=db.execute('SELECT migration_key FROM autotrader_v3_registry_migrations WHERE migration_key=?',
            (_LEGACY_REGISTRY_MIGRATION_V1,)).fetchone()
        if marker is not None:return

        for e in v2:
            db.execute('DELETE FROM autotrader_v3_engine_instances WHERE instance_id=?',(str(e.pilot_key),))

        for e in v3:
            pilot=str(e.pilot_key);account=str(e.account_id);uic=int(e.uic);asset=str(e.asset_type)
            by_id=db.execute('''SELECT instance_id,account_id,uic,asset_type FROM autotrader_v3_engine_instances
              WHERE instance_id=?''',(pilot,)).fetchone()
            occupied=db.execute('''SELECT instance_id FROM autotrader_v3_engine_instances
              WHERE account_id=? AND enabled=TRUE AND instance_id<>?''',(account,pilot)).fetchone()
            if occupied is not None:
                other=str(occupied['instance_id'] if isinstance(occupied,dict) else occupied[0])
                raise RuntimeError(f'V3 legacy identity migration conflict: account {account} is already attached to {other}')
            boundary=db.execute('''SELECT instance_id FROM autotrader_v3_engine_instances
              WHERE account_id=? AND uic=? AND asset_type=? AND instance_id<>?''',(account,uic,asset,pilot)).fetchone()
            if boundary is not None:
                other=str(boundary['instance_id'] if isinstance(boundary,dict) else boundary[0])
                raise RuntimeError(f'V3 legacy identity migration conflict: exact boundary is already attached to {other}')
            if by_id is None:
                db.execute('''INSERT INTO autotrader_v3_engine_instances(
                  instance_id,account_id,uic,asset_type,market_id,instrument_id,market_name,enabled)
                  VALUES(?,?,?,?,?,?,?,TRUE)''',(pilot,account,uic,asset,int(e.market_id),int(e.instrument_id),str(e.market_name)))
            else:
                g=lambda k,n:by_id[k] if isinstance(by_id,dict) else by_id[n]
                if str(g('account_id',1))!=account or int(g('uic',2))!=uic or str(g('asset_type',3))!=asset:
                    raise RuntimeError(f'V3 legacy identity migration conflict: {pilot} changed exact broker boundary')
                db.execute('''UPDATE autotrader_v3_engine_instances SET enabled=TRUE,updated_at=CURRENT_TIMESTAMP
                  WHERE instance_id=?''',(pilot,))

        db.execute('INSERT INTO autotrader_v3_registry_migrations(migration_key) VALUES(?)',
            (_LEGACY_REGISTRY_MIGRATION_V1,))


def bootstrap_v3_instances_from_enrollments_v1(*,db_path='pricegauger.db'):
    ensure_v3_instance_registry_v1(db_path=db_path)
    current=load_v3_instances_v1(db_path=db_path)
    # Isolated SQLite callers/tests that already created explicit V3 instances do not
    # need the production legacy migration bridge.
    if current and not using_postgres():
        return current
    if not _legacy_registry_migration_complete_v1(db_path=db_path):
        _migrate_legacy_registry_rows_v1(load_active_strategy_enrollments_v2(),db_path=db_path)
    return load_v3_instances_v1(db_path=db_path)
