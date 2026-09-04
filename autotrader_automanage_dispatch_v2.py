from __future__ import annotations

import logging
import time

from autotrader_ai_live_runtime_v1 import run_ai_live_strategy_once_v1
from autotrader_automanage_runtime_v2 import run_automanage_strategy_once_v2
from autotrader_cadence_v2 import sleep_to_fixed_start_cadence_v2
from autotrader_fast_live_runtime_v2 import FastLiveCycleV2, run_fast_live_strategy_once_v2
from autotrader_macd_hybrid_v1 import run_macd_hybrid_live_once_v1
from autotrader_macd_timeframe_live_v1 import run_macd_timeframe_live_once_v1
from autotrader_mtf_flip_live_runtime_v2 import run_mtf_flip_live_strategy_once_v2
from autotrader_mtf_live_runtime_v2 import run_mtf_live_strategy_once_v2
from autotrader_mtf_short_live_runtime_v2 import run_mtf_short_live_strategy_once_v2
from autotrader_risk_control_v2 import _position_observations_v2
from autotrader_strategy_catalog_v2 import (
    AI_BASELINE_STRATEGY_V2,
    MACD_1M_FLIP_STRATEGY_V2,
    MACD_2M_FLIP_STRATEGY_V2,
    MACD_15M_FLIP_STRATEGY_V2,
    MACD_HYBRID_EXIT_1M_ENTRY_2M_STRATEGY_V2,
    MACD_HYBRID_EXIT_1M_ENTRY_5M_STRATEGY_V2,
    MTF_LONG_FLAT_STRATEGY_V2,
    MTF_LONG_SHORT_FLIP_STRATEGY_V2,
    MTF_SHORT_FLAT_STRATEGY_V2,
    STRONG_COCKTAIL_STRATEGY_V2,
)
from autotrader_strategy_enrollment_v2 import EXECUTION_MODE_LIVE, load_active_strategy_enrollments_v2
from database import using_postgres
from saxo_provider import configured_client


LOGGER = logging.getLogger("pricegauger.autotrader.automanage_dispatch_v2")
FAST_LIVE_STRATEGIES = {STRONG_COCKTAIL_STRATEGY_V2, MACD_1M_FLIP_STRATEGY_V2}
TIMEFRAME_MACD_LIVE_STRATEGIES = {MACD_2M_FLIP_STRATEGY_V2, MACD_15M_FLIP_STRATEGY_V2}
HYBRID_LIVE_STRATEGIES = {
    MACD_HYBRID_EXIT_1M_ENTRY_2M_STRATEGY_V2,
    MACD_HYBRID_EXIT_1M_ENTRY_5M_STRATEGY_V2,
}
_FAST_LOG_FINGERPRINTS: dict[str, tuple[object, ...]] = {}


def _log_fast_cycle_if_changed_v2(cycle: FastLiveCycleV2) -> None:
    """Emit one causal line per meaningful fast/AI LIVE state change, not per poll."""
    meaningful = bool(
        cycle.request_created
        or cycle.reason.startswith("TARGET_")
        or cycle.reason == "PENDING_TRANSITION_CONTINUED"
    )
    if not meaningful:
        return
    fingerprint = (
        cycle.reason,
        cycle.desired_direction,
        cycle.observed_direction,
        cycle.pending_target_direction,
        cycle.action_at,
        cycle.request_created,
    )
    if _FAST_LOG_FINGERPRINTS.get(cycle.pilot_key) == fingerprint:
        return
    _FAST_LOG_FINGERPRINTS[cycle.pilot_key] = fingerprint
    LOGGER.info(
        "Fast LIVE transition pilot=%s strategy=%s reason=%s observed=%s desired=%s pending=%s request_created=%s action_at=%s",
        cycle.pilot_key,
        cycle.strategy_key,
        cycle.reason,
        cycle.observed_direction,
        cycle.desired_direction,
        cycle.pending_target_direction or "none",
        cycle.request_created,
        cycle.action_at.isoformat(),
    )


def run_automanage_strategy_cycle_v2(*, db_path: str = "pricegauger.db") -> tuple[int, int]:
    """Dispatch active LIVE pilots without giving signal engines order authority."""
    if not using_postgres():
        return (0, 0)
    enrollments = tuple(
        item
        for item in load_active_strategy_enrollments_v2()
        if item.execution_mode == EXECUTION_MODE_LIVE and item.enabled
    )
    if not enrollments:
        return (0, 0)
    client = configured_client()
    if client is None:
        raise RuntimeError("Saxo client is not configured")
    observations = _position_observations_v2(client)

    evaluated = 0
    failed = 0
    for enrollment in enrollments:
        try:
            if enrollment.strategy_key == AI_BASELINE_STRATEGY_V2:
                cycle = run_ai_live_strategy_once_v1(
                    enrollment,
                    db_path=db_path,
                    observations=observations,
                )
                _log_fast_cycle_if_changed_v2(cycle)
            elif enrollment.strategy_key in HYBRID_LIVE_STRATEGIES:
                cycle = run_macd_hybrid_live_once_v1(
                    enrollment,
                    db_path=db_path,
                    observations=observations,
                )
                _log_fast_cycle_if_changed_v2(cycle)
            elif enrollment.strategy_key in TIMEFRAME_MACD_LIVE_STRATEGIES:
                cycle = run_macd_timeframe_live_once_v1(
                    enrollment,
                    db_path=db_path,
                    observations=observations,
                )
                _log_fast_cycle_if_changed_v2(cycle)
            elif enrollment.strategy_key in FAST_LIVE_STRATEGIES:
                cycle = run_fast_live_strategy_once_v2(
                    enrollment,
                    db_path=db_path,
                    observations=observations,
                )
                _log_fast_cycle_if_changed_v2(cycle)
            elif enrollment.strategy_key == MTF_LONG_FLAT_STRATEGY_V2:
                run_mtf_live_strategy_once_v2(
                    enrollment,
                    db_path=db_path,
                    observations=observations,
                )
            elif enrollment.strategy_key == MTF_SHORT_FLAT_STRATEGY_V2:
                run_mtf_short_live_strategy_once_v2(
                    enrollment,
                    db_path=db_path,
                    observations=observations,
                )
            elif enrollment.strategy_key == MTF_LONG_SHORT_FLIP_STRATEGY_V2:
                run_mtf_flip_live_strategy_once_v2(
                    enrollment,
                    db_path=db_path,
                    observations=observations,
                )
            else:
                run_automanage_strategy_once_v2(
                    enrollment,
                    db_path=db_path,
                    observations=observations,
                )
            evaluated += 1
        except Exception as exc:
            failed += 1
            LOGGER.warning(
                "AutoManage strategy evaluation failed pilot=%s strategy=%s: %s",
                enrollment.pilot_key,
                enrollment.strategy_key,
                exc,
                exc_info=True,
            )
    return evaluated, failed


def run_automanage_strategy_forever_v2(
    *,
    db_path: str = "pricegauger.db",
    interval_seconds: int = 15,
) -> None:
    interval = max(5, int(interval_seconds))
    while True:
        started = time.monotonic()
        try:
            run_automanage_strategy_cycle_v2(db_path=db_path)
        except Exception as exc:
            LOGGER.warning("AutoManage strategy dispatch cycle failed: %s", exc, exc_info=True)
        sleep_to_fixed_start_cadence_v2(started, interval)


__all__ = ["run_automanage_strategy_cycle_v2", "run_automanage_strategy_forever_v2"]
