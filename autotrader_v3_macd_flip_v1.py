"""V3 MACD Flip: pure V2-equivalent 12/26/9 CLOSED-bar cross signal.

This module does not import V2 LIVE, Saxo, order placement or any database.
It emits only a V3 target. The existing V3 execution/reconciliation layer
alone owns CLOSE -> broker-confirmed FLAT -> OPEN.
"""
from __future__ import annotations

from autotrader_macd_dry_run_v2 import MacdObservationV2
from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_macd_trailing_v1 import (
    MacdTrailingConfigV3, MacdTrailingDecisionV3,
)

STRATEGY_KEY_V3 = "macd-flip-v1"


def macd_flip_target_v3(
    *,
    current_target: TargetInventoryV3,
    observation: MacdObservationV2,
    previous_observation: MacdObservationV2 | None = None,
    config: MacdTrailingConfigV3 = MacdTrailingConfigV3(),
) -> MacdTrailingDecisionV3:
    """MACD cross only: HOLD until the next genuine closed-bar opposite cross.

    Exact V2 crossover inequalities:
      <= 0 -> > 0 : LONG
      >= 0 -> < 0 : SHORT

    No entry on boot/config switch without a previous *completed* observation.
    No intrabar changes, momentum scaling, pyramiding, trailing, or fee-dependent
    signal logic. Each signal targets exactly one Saxo-legal tranche, NOT the
    default V3 10-tranche ceiling. An opposite current inventory is replaced
    through V3's separate broker-confirmed flat-first execution path.
    """
    spread = float(observation.spread)
    current = TargetInventoryV3(current_target.amount)
    if previous_observation is None:
        return MacdTrailingDecisionV3(
            current, "HOLD_BOOTSTRAP",
            "No previous completed MACD bar: await a genuine cross", spread,
        )

    previous = float(previous_observation.spread)
    if previous <= 0.0 < spread:
        target = TargetInventoryV3(float(config.tranche))
        action = "CROSS_UP"
        side = "LONG"
    elif previous >= 0.0 > spread:
        target = TargetInventoryV3(-float(config.tranche))
        action = "CROSS_DOWN"
        side = "SHORT"
    else:
        return MacdTrailingDecisionV3(
            current, "HOLD_UNTIL_CROSS",
            f"MACD unchanged regime; prior={previous:+.6f}, current={spread:+.6f}",
            spread,
        )

    # Never introduce a larger position just because V3's generic strategy
    # amount config has max_inventory=10 * tranche.
    if abs(target.amount) > config.max_inventory + 1e-9:
        raise ValueError("MACD Flip target exceeds legal strategy inventory cap")
    return MacdTrailingDecisionV3(
        target, action,
        f"V2-equivalent confirmed closed MACD 12/26/9 {side} cross; "
        f"one legal tranche {config.tranche:g}; execution flat-first",
        spread,
    )


__all__ = ["STRATEGY_KEY_V3", "macd_flip_target_v3"]
