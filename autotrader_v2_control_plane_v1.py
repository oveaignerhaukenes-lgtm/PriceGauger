from __future__ import annotations

"""Canonical operator-facing authority transitions for AutoTrader V2.

The control plane owns the account->engine claim before mutating V2 runtime
authority. Raw V2 authority primitives remain available to worker/recovery code,
but operator UI should use this module.
"""

from dataclasses import dataclass

from autotrader_engine_account_ownership_v1 import ENGINE_V2, claim_account_v1, release_account_v1
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
        claim_account_v1(account_id, ENGINE_V2, owner_key, db_path=db_path)
        try:
            set_position_management_enabled_v1(enrollment, True)
            set_auto_manage_enabled_v1(enrollment, True)
        except Exception:
            # Roll back only the claim introduced for this transition. The raw
            # authority functions are deliberately left unchanged for recovery.
            release_account_v1(account_id, ENGINE_V2, owner_key, db_path=db_path)
            raise
    else:
        # Remove execution authority before releasing the ownership boundary.
        set_auto_manage_enabled_v1(enrollment, False)
        set_position_management_enabled_v1(enrollment, False)
        try:
            release_account_v1(account_id, ENGINE_V2, owner_key, db_path=db_path)
        except RuntimeError:
            # A mismatching owner is an architecture violation and must remain
            # visible rather than silently deleting another controller's claim.
            raise
    return authority_state_v2(enrollment)
