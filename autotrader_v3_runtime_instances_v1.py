from __future__ import annotations

from dataclasses import dataclass

from autotrader_v3_config_v1 import load_autotrader_config_v3
from autotrader_v3_instance_registry_v1 import bootstrap_v3_instances_from_enrollments_v1


@dataclass(frozen=True, slots=True)
class V3RuntimeInstanceV1:
    pilot_key: str
    account_id: str
    uic: int
    asset_type: str
    market_id: int
    instrument_id: int
    market_name: str
    strategy_key: str


def load_v3_runtime_instances_v1(*, db_path: str = "pricegauger.db") -> tuple[V3RuntimeInstanceV1, ...]:
    instances=bootstrap_v3_instances_from_enrollments_v1(db_path=db_path)
    result=[]
    for item in instances:
        config=load_autotrader_config_v3(item.instance_id,db_path=db_path)
        result.append(V3RuntimeInstanceV1(
            pilot_key=item.instance_id,account_id=item.account_id,uic=item.uic,asset_type=item.asset_type,
            market_id=item.market_id,instrument_id=item.instrument_id,market_name=item.market_name,
            strategy_key=config.strategy_key,
        ))
    return tuple(result)
