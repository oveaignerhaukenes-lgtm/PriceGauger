from __future__ import annotations

"""Canonical operator-facing authority transitions for AutoTrader V2."""

from dataclasses import dataclass

from autotrader_engine_account_ownership_v1 import (
    ENGINE_V2,
    claim_account_v1,
    load_account_owner_v1,
    release_account_v1,
)
from autotrader_manage_control_v1 import (
    auto_manage_enabled_v1,
    position_management_enabled_v1,
    set_auto_manage_enabled_v1,
    set_position_management_enabled_v1,
)


@dataclass(frozen=True, slots=True)
class V2AuthorityStateV1:
    owner_key: str
    live_armed: bool
    position_management_enabled: bool
    auto_manage_enabled: bool


def authority_state_v2(enrollment) -> V2AuthorityStateV1:
    position_enabled = bool(position_management_enabled_v1(enrollment))
    auto_enabled = bool(auto_manage_enabled_v1(enrollment))
    return V2AuthorityStateV1(
        owner_key=str(enrollment.pilot_key),
        live_armed=bool(position_enabled and auto_enabled),
        position_management_enabled=position_enabled,
        auto_manage_enabled=auto_enabled,
    )


def set_live_enabled_v2(enrollment, enabled: bool, *, db_path: str = "pricegauger.db") -> V2AuthorityStateV1:
    account_id = str(enrollment.account_id).strip()
    owner_key = str(enrollment.pilot_key).strip()
    if enabled:
        previous_owner = load_account_owner_v1(account_id, db_path=db_path)
        claim_account_v1(account_id, ENGINE_V2, owner_key, db_path=db_path)
        claim_created = previous_owner is None
        try:
            set_position_management_enabled_v1(enrollment, True)
            set_auto_manage_enabled_v1(enrollment, True)
        except Exception:
            if claim_created:
                release_account_v1(account_id, ENGINE_V2, owner_key, db_path=db_path)
            raise
    else:
        set_auto_manage_enabled_v1(enrollment, False)
        set_position_management_enabled_v1(enrollment, False)
        owner = load_account_owner_v1(account_id, db_path=db_path)
        if owner is not None:
            release_account_v1(account_id, ENGINE_V2, owner_key, db_path=db_path)
    return authority_state_v2(enrollment)
