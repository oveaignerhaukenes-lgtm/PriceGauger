from __future__ import annotations

"""Canonical operator-facing authority transitions for AutoTrader V3."""

from dataclasses import dataclass

from autotrader_engine_account_ownership_v1 import (
    ENGINE_V3,
    claim_account_v1,
    load_account_owner_v1,
    release_account_v1,
)
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


def set_live_enabled_v3(
    trader_id: str,
    enabled: bool,
    *,
    account_id: str | None = None,
    db_path: str = "pricegauger.db",
) -> V3AuthorityStateV1:
    if enabled:
        if not account_id:
            raise ValueError("V3 LIVE requires an explicit Saxo account ownership boundary")
        previous_owner = load_account_owner_v1(account_id, db_path=db_path)
        claim_account_v1(account_id, ENGINE_V3, trader_id, db_path=db_path)
        claim_created = previous_owner is None
        try:
            set_sim_authority_v3(trader_id, False, db_path=db_path)
            set_live_authority_v3(trader_id, True, db_path=db_path)
        except Exception:
            if claim_created:
                release_account_v1(account_id, ENGINE_V3, trader_id, db_path=db_path)
            raise
    else:
        set_live_authority_v3(trader_id, False, db_path=db_path)
        if account_id:
            owner = load_account_owner_v1(account_id, db_path=db_path)
            if owner is not None:
                release_account_v1(account_id, ENGINE_V3, trader_id, db_path=db_path)
    return authority_state_v3(trader_id, db_path=db_path)


def set_sim_enabled_v3(
    trader_id: str,
    enabled: bool,
    *,
    account_id: str | None = None,
    db_path: str = "pricegauger.db",
) -> V3AuthorityStateV1:
    if enabled:
        set_live_authority_v3(trader_id, False, db_path=db_path)
        if account_id:
            owner = load_account_owner_v1(account_id, db_path=db_path)
            if owner is not None:
                release_account_v1(account_id, ENGINE_V3, trader_id, db_path=db_path)
    set_sim_authority_v3(trader_id, enabled, db_path=db_path)
    return authority_state_v3(trader_id, db_path=db_path)
