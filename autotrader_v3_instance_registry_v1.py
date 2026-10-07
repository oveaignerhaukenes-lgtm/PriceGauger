from __future__ import annotations
from dataclasses import dataclass
from uuid import NAMESPACE_URL,uuid5

from autotrader_engine_identity_v1 import ENGINE_V2,ENGINE_V3,enrollment_engine_v1
from autotrader_strategy_enrollment_v2 import EXECUTION_MODE_LIVE,load_active_strategy_enrollments_v2
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
    requested=str(instance_id or '').strip() or None
    deterministic=str(uuid5(NAMESPACE_URL,f'pricegauger:v3:{account}:{int(template.uic)}:{template.asset_type}'))
    with connect(db_path) as db:
        existing=db.execute('SELECT instance_id FROM autotrader_v3_engine_instances WHERE account_id=? AND enabled=TRUE',(account,)).fetchone()
        if existing is not None:raise ValueError('This Saxo account is already attached to a V3 instance')
        boundary=db.execute('''SELECT instance_id FROM autotrader_v3_engine_instances
          WHERE account_id=? AND uic=? AND asset_type=? ORDER BY created_at ASC LIMIT 1''',
          (account,int(template.uic),str(template.asset_type))).fetchone()
        boundary_id=None if boundary is None else str(boundary['instance_id'] if isinstance(boundary,dict) else boundary[0])
        if requested and boundary_id and requested!=boundary_id:
            raise RuntimeError('requested V3 identity conflicts with historical broker boundary')
        identity=requested or boundary_id or deterministic
        historical=db.execute('''SELECT account_id,uic,asset_type FROM autotrader_v3_engine_instances
          WHERE instance_id=?''',(identity,)).fetchone()
        if historical is None:
            db.execute('''INSERT INTO autotrader_v3_engine_instances(instance_id,account_id,uic,asset_type,market_id,instrument_id,market_name,enabled)
              VALUES(?,?,?,?,?,?,?,TRUE)''',(identity,account,int(template.uic),str(template.asset_type),int(template.market_id),int(template.instrument_id),str(template.market_name)))
        else:
            g=lambda k,n:historical[k] if isinstance(historical,dict) else historical[n]
            if str(g('account_id',0))!=account or int(g('uic',1))!=int(template.uic) or str(g('asset_type',2))!=str(template.asset_type):
                raise RuntimeError('stable V3 identity collides with another broker boundary')
            db.execute('''UPDATE autotrader_v3_engine_instances SET
              market_id=?,instrument_id=?,market_name=?,enabled=TRUE,updated_at=CURRENT_TIMESTAMP
              WHERE instance_id=?''',(int(template.market_id),int(template.instrument_id),str(template.market_name),identity))
    return next(i for i in load_v3_instances_v1(db_path=db_path) if i.instance_id==identity)


def disable_v3_instance_v1(*,instance_id:str,db_path='pricegauger.db')->None:
    """Disable one V3 registry row without deleting its historical identity/config."""
    ensure_v3_instance_registry_v1(db_path=db_path);identity=str(instance_id or '').strip()
    if not identity:raise ValueError('instance_id required')
    with connect(db_path) as db:
        cursor=db.execute('''UPDATE autotrader_v3_engine_instances
          SET enabled=FALSE,updated_at=CURRENT_TIMESTAMP
          WHERE instance_id=? AND enabled=TRUE''',(identity,))
        if cursor.rowcount!=1:raise LookupError('enabled V3 instance not found')


def replace_v3_instance_boundary_v1(*,instance_id:str,template,db_path='pricegauger.db'):
    """Atomically replace one enabled account's broker boundary with a new V3 identity.

    Authority/pending-order safety belongs to the caller. This registry primitive only
    guarantees that the old row is disabled and the new exact boundary is enabled in
    one database transaction, so an account is never left with two enabled instances.
    """
    ensure_v3_instance_registry_v1(db_path=db_path);old_id=str(instance_id or '').strip()
    if not old_id:raise ValueError('instance_id required')
    with connect(db_path) as db:
        row=db.execute('''SELECT account_id,uic,asset_type,market_id,instrument_id,market_name
          FROM autotrader_v3_engine_instances WHERE instance_id=? AND enabled=TRUE''',(old_id,)).fetchone()
        if row is None:raise LookupError('enabled V3 instance not found')
        g=lambda k,n:row[k] if isinstance(row,dict) else row[n]
        account=str(g('account_id',0));old_uic=int(g('uic',1));old_asset=str(g('asset_type',2))
        new_uic=int(template.uic);new_asset=str(template.asset_type)
        new_market_id=int(template.market_id);new_instrument_id=int(template.instrument_id);new_market_name=str(template.market_name)
        if old_uic==new_uic and old_asset==new_asset and int(g('market_id',3))==new_market_id and int(g('instrument_id',4))==new_instrument_id:
            return V3EngineInstanceV1(old_id,account,old_uic,old_asset,int(g('market_id',3)),int(g('instrument_id',4)),str(g('market_name',5)),True)
        identity=str(uuid5(NAMESPACE_URL,f'pricegauger:v3:{account}:{new_uic}:{new_asset}'))
        occupied=db.execute('''SELECT instance_id FROM autotrader_v3_engine_instances
          WHERE account_id=? AND enabled=TRUE AND instance_id<>?''',(account,old_id)).fetchone()
        if occupied is not None:raise RuntimeError('Saxo account has another enabled V3 instance')
        boundary=db.execute('''SELECT instance_id FROM autotrader_v3_engine_instances
          WHERE account_id=? AND uic=? AND asset_type=? AND instance_id NOT IN (?,?)''',
          (account,new_uic,new_asset,old_id,identity)).fetchone()
        if boundary is not None:raise RuntimeError('target V3 broker boundary already belongs to another instance')
        historical=db.execute('''SELECT account_id,uic,asset_type FROM autotrader_v3_engine_instances
          WHERE instance_id=?''',(identity,)).fetchone()
        if historical is not None:
            h=lambda k,n:historical[k] if isinstance(historical,dict) else historical[n]
            if str(h('account_id',0))!=account or int(h('uic',1))!=new_uic or str(h('asset_type',2))!=new_asset:
                raise RuntimeError('stable V3 identity collides with another broker boundary')
        db.execute('''UPDATE autotrader_v3_engine_instances SET enabled=FALSE,updated_at=CURRENT_TIMESTAMP
          WHERE instance_id=?''',(old_id,))
        if historical is None:
            db.execute('''INSERT INTO autotrader_v3_engine_instances(
              instance_id,account_id,uic,asset_type,market_id,instrument_id,market_name,enabled)
              VALUES(?,?,?,?,?,?,?,TRUE)''',
              (identity,account,new_uic,new_asset,new_market_id,new_instrument_id,new_market_name))
        else:
            db.execute('''UPDATE autotrader_v3_engine_instances SET
              market_id=?,instrument_id=?,market_name=?,enabled=TRUE,updated_at=CURRENT_TIMESTAMP
              WHERE instance_id=?''',(new_market_id,new_instrument_id,new_market_name,identity))
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
    v3=tuple(e for e in enrollments if enrollment_engine_v1(e)==ENGINE_V3 and str(e.execution_mode)==EXECUTION_MODE_LIVE)
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
