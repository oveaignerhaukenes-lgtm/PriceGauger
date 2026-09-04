from __future__ import annotations

"""Simple-Core facade for the durable AutoManager activity log."""

import autotrader_activity_log_legacy_v2 as _legacy
from autotrader_activity_log_legacy_v2 import *  # noqa: F401,F403


ENGINE_AUTOMANAGER = "AutoManager"
_legacy.ENGINE_AUTOMANAGER = ENGINE_AUTOMANAGER
_original_build = _legacy.build_automanager_lifecycle_status_v2


def build_automanager_lifecycle_status_v2(
    enrollment,
    *,
    observed_direction: str,
    latest_strategy_close_signal=None,
    latest_strategy_close_at=None,
    latest_guardian_reason=None,
    latest_guardian_close_at=None,
    pending_action=None,
    pending_status=None,
    pending_block_reason=None,
    exact_close_authority=None,
):
    """Describe runtime state without exposing legacy user-confirmation gates."""
    direction = str(observed_direction or "FLAT").upper()
    if direction != "FLAT" and exact_close_authority is False:
        return (
            f"{direction} · registrerer AutoManager-basis",
            "AutoManager registrerer eksakt Saxo-basis automatisk før neste CLOSE; ingen brukerbekreftelse kreves.",
        )

    status, next_step = _original_build(
        enrollment,
        observed_direction=observed_direction,
        latest_strategy_close_signal=latest_strategy_close_signal,
        latest_strategy_close_at=latest_strategy_close_at,
        latest_guardian_reason=latest_guardian_reason,
        latest_guardian_close_at=latest_guardian_close_at,
        pending_action=pending_action,
        pending_status=pending_status,
        pending_block_reason=pending_block_reason,
        exact_close_authority=exact_close_authority,
    )
    status = status.replace("30m MACD-kryss", "strategisignal")
    next_step = next_step.replace(
        "Overvåker neste lukkede 30m-bar; ",
        "Overvåker valgt strategi; ",
    )
    next_step = next_step.replace(" MACD-kryss", " signal")
    next_step = next_step.replace("automatisk re-entry er armed", "automatisk OPEN/re-entry er aktiv")
    return status, next_step


_legacy.build_automanager_lifecycle_status_v2 = build_automanager_lifecycle_status_v2
load_automanager_activity_log_v2 = _legacy.load_automanager_activity_log_v2

__all__ = list(_legacy.__all__)
