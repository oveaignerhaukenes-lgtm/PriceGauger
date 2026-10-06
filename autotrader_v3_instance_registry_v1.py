from __future__ import annotations
from dataclasses import dataclass
from uuid import NAMESPACE_URL,uuid5
from autotrader_strategy_enrollment_v2 import load_active_strategy_enrollments_v2
from database import connect

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
        # Account assignment is an instance-level boundary: one Saxo account cannot be
        # attached to two enabled V3 instances, even when their instruments differ.
        db.execute('''CREATE UNIQUE INDEX IF NOT EXISTS uq_v3_enabled_account
          ON autotrader_v3_engine_instances(account_id) WHERE enabled=TRUE''')

def _row(row):
    g=lambda k,n:row[k] if isinstance(row,dict) else row[n]
    return V3EngineInstanceV1(str(g('instance_id',0)),str(g('account_id',1)),int(g('uic',2)),str(g('asset_type',3)),int(g('market_id',4)),int(g('instrument_id',5)),str(g('market_name',6)),bool(g('enabled',7)))

def load_v3_instances_v1(*,db_path='pricegauger.db'):
    ensure_v3_instance_registry_v1(db_path=db_path)
    with connect(db_path) as db:rows=db.execute('''SELECT instance_id,account_id,uic,asset_type,market_id,instrument_id,market_name,enabled FROM autotrader_v3_engine_instances WHERE enabled=TRUE ORDER BY created_at,instance_id''').fetchall()
    return tuple(_row(r) for r in rows)

def create_v3_instance_v1(*,account_id:str,template,db_path='pricegauger.db',instance_id=None):
    ensure_v3_instance_registry_v1(db_path=db_path);account=str(account_id or '').strip()
    if not account:raise ValueError('V3 instance requires account_id')
    identity=str(instance_id or uuid5(NAMESPACE_URL,f'pricegauger:v3:{account}:{int(template.uic)}:{template.asset_type}'))
    with connect(db_path) as db:
        existing=db.execute('SELECT instance_id FROM autotrader_v3_engine_instances WHERE account_id=? AND enabled=TRUE',(account,)).fetchone()
        if existing is not None:raise ValueError('This Saxo account is already attached to a V3 instance')
        db.execute('''INSERT INTO autotrader_v3_engine_instances(instance_id,account_id,uic,asset_type,market_id,instrument_id,market_name,enabled) VALUES(?,?,?,?,?,?,?,TRUE)''',(identity,account,int(template.uic),str(template.asset_type),int(template.market_id),int(template.instrument_id),str(template.market_name)))
    return next(i for i in load_v3_instances_v1(db_path=db_path) if i.instance_id==identity)

def bootstrap_v3_instances_from_enrollments_v1(*,db_path='pricegauger.db'):
    ensure_v3_instance_registry_v1(db_path=db_path);current=load_v3_instances_v1(db_path=db_path)
    if current:return current
    for e in load_active_strategy_enrollments_v2():
        try:create_v3_instance_v1(account_id=e.account_id,template=e,instance_id=e.pilot_key,db_path=db_path)
        except ValueError:pass
    return load_v3_instances_v1(db_path=db_path)
