from __future__ import annotations

from datetime import datetime, timezone
import logging

import autotrader_automanage_dispatch_v2 as dispatch
from autotrader_fast_live_runtime_v2 import FastLiveCycleV2


def _cycle() -> FastLiveCycleV2:
    return FastLiveCycleV2(
        pilot_key="pilot-1",
        strategy_key="strong-cocktail-shadow-v1",
        desired_direction="SHORT",
        observed_direction="FLAT",
        pending_target_direction="SHORT",
        action_at=datetime(2026, 9, 3, 18, 30, tzinfo=timezone.utc),
        processed=False,
        request_created=True,
        bootstrap=False,
        reason="PENDING_TRANSITION_CONTINUED",
    )


def test_fast_live_transition_log_is_causal_and_deduplicated(caplog) -> None:
    dispatch._FAST_LOG_FINGERPRINTS.clear()
    caplog.set_level(logging.INFO, logger="pricegauger.autotrader.automanage_dispatch_v2")

    dispatch._log_fast_cycle_if_changed_v2(_cycle())
    dispatch._log_fast_cycle_if_changed_v2(_cycle())

    messages = [record.getMessage() for record in caplog.records if "Fast LIVE transition" in record.getMessage()]
    assert len(messages) == 1
    assert "observed=FLAT" in messages[0]
    assert "desired=SHORT" in messages[0]
    assert "request_created=True" in messages[0]
