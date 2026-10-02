from __future__ import annotations

"""Canonical operator-facing authority transitions for AutoTrader V3."""

from dataclasses import dataclass

from autotrader_v3_live_authority_v1 import live_authority_armed_v3, set_live_authority_v3
from autotrader_v3_sim_authority_v1 import sim_authority_armed_v3, set_sim_authority_v3

@dataclass(frozen=True, slots=True)
class V3AuthorityStateV1:
    trader_id: str
    live_armed: bool
    sim_armed: bool

def authority_state_v3(trader_id: str, *, db_path: str = "pricegauger.db") -> V3AuthorityStateV1:
    return V3AuthorityStateV1(
        trader_id=trader_id,
        live_armed=live_authority_armed_v3(trader_id, db_path=db_path),
        sim_armed=sim_authority_armed_v3(trader_id, db_path=db_path),
    )

def set_live_enabled_v3(trader_id: str, enabled: bool, *, db_path: str = "pricegauger.db") -> V3AuthorityStateV1:
    if enabled:
        set_sim_authority_v3(trader_id, False, db_path=db_path)
    set_live_authority_v3(trader_id, enabled, db_path=db_path)
    return authority_state_v3(trader_id, db_path=db_path)

def set_sim_enabled_v3(trader_id: str, enabled: bool, *, db_path: str = "pricegauger.db") -> V3AuthorityStateV1:
    if enabled:
        set_live_authority_v3(trader_id, False, db_path=db_path)
    set_sim_authority_v3(trader_id, enabled, db_path=db_path)
    return authority_state_v3(trader_id, db_path=db_path)
