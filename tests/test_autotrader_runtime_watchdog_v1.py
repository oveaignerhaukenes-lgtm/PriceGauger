from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from autotrader_runtime_watchdog_v1 import (
    AuthoritativeCrossV1,
    WatchdogInputV1,
    evaluate_watchdog_contracts_v1,
)


NOW = datetime(2026, 9, 21, 0, 40, tzinfo=timezone.utc)


def _snapshot(**changes) -> WatchdogInputV1:
    values = {
        "pilot_key": "pilot-1",
        "strategy_key": "macd-norm-v1",
        "market_name": "US Tech 100 NAS · Saxo 4912",
        "desired_direction": "LONG",
        "observed_direction": "LONG",
        "pending_target_direction": None,
        "intent_signal_at": NOW - timedelta(seconds=30),
        "intent_signal": "MACD_NORM:LONG:authoritative_cross=LONG",
        "latest_request_id": None,
        "latest_request_action": None,
        "latest_request_status": None,
        "latest_request_updated_at": None,
        "authoritative_cross": None,
        "authoritative_cross_acknowledged": False,
        "auto_manage_enabled": True,
    }
    values.update(changes)
    return WatchdogInputV1(**values)


def test_opposite_saxo_exposure_after_target_is_critical() -> None:
    findings = evaluate_watchdog_contracts_v1(
        _snapshot(
            observed_direction="SHORT",
            intent_signal_at=NOW - timedelta(seconds=60),
        ),
        now=NOW,
    )

    by_code = {item.code: item for item in findings}
    assert by_code["OPPOSITE_EXPOSURE_AFTER_TARGET"].severity == "CRITICAL"
    assert "Saxo remains SHORT" in by_code["OPPOSITE_EXPOSURE_AFTER_TARGET"].summary


def test_recent_target_mismatch_gets_execution_grace() -> None:
    findings = evaluate_watchdog_contracts_v1(
        _snapshot(
            observed_direction="SHORT",
            intent_signal_at=NOW - timedelta(seconds=20),
        ),
        now=NOW,
    )
    assert findings == ()


def test_unacknowledged_authoritative_cross_is_detected_independently() -> None:
    cross = AuthoritativeCrossV1(
        direction="LONG",
        occurred_at=NOW - timedelta(seconds=60),
        timeframe_minutes=5,
        previous_spread=-0.4,
        current_spread=0.2,
    )
    findings = evaluate_watchdog_contracts_v1(
        _snapshot(
            desired_direction="SHORT",
            observed_direction="SHORT",
            authoritative_cross=cross,
            authoritative_cross_acknowledged=False,
            intent_signal_at=NOW - timedelta(minutes=10),
            intent_signal="OLD_SHORT",
        ),
        now=NOW,
    )

    by_code = {item.code: item for item in findings}
    assert by_code["AUTHORITATIVE_CROSS_TARGET_MISMATCH"].severity == "CRITICAL"
    assert by_code["AUTHORITATIVE_CROSS_TARGET_MISMATCH"].evidence["cross_direction"] == "LONG"


def test_acknowledged_cross_is_not_retroactively_flagged_after_later_early_reversal() -> None:
    cross = AuthoritativeCrossV1(
        direction="LONG",
        occurred_at=NOW - timedelta(minutes=4),
        timeframe_minutes=5,
        previous_spread=-0.1,
        current_spread=0.1,
    )
    findings = evaluate_watchdog_contracts_v1(
        _snapshot(
            desired_direction="SHORT",
            observed_direction="SHORT",
            authoritative_cross=cross,
            authoritative_cross_acknowledged=True,
            intent_signal_at=NOW - timedelta(seconds=20),
            intent_signal="EARLY_SHORT",
        ),
        now=NOW,
    )
    assert all(item.code != "AUTHORITATIVE_CROSS_TARGET_MISMATCH" for item in findings)


def test_position_opposite_cross_requires_current_target_to_still_follow_cross() -> None:
    cross = AuthoritativeCrossV1(
        direction="LONG",
        occurred_at=NOW - timedelta(minutes=3),
        timeframe_minutes=5,
        previous_spread=-0.1,
        current_spread=0.2,
    )
    findings = evaluate_watchdog_contracts_v1(
        _snapshot(
            desired_direction="LONG",
            observed_direction="SHORT",
            authoritative_cross=cross,
            authoritative_cross_acknowledged=True,
            intent_signal_at=NOW - timedelta(minutes=3),
        ),
        now=NOW,
    )
    assert "AUTHORITATIVE_CROSS_POSITION_OPPOSITE" in {item.code for item in findings}


def test_pending_and_execution_lifecycle_stalls_are_recorded() -> None:
    findings = evaluate_watchdog_contracts_v1(
        _snapshot(
            desired_direction="LONG",
            observed_direction="FLAT",
            pending_target_direction="LONG",
            intent_signal_at=NOW - timedelta(minutes=3),
            latest_request_id="req-1",
            latest_request_action="OPEN",
            latest_request_status="SUBMITTING",
            latest_request_updated_at=NOW - timedelta(seconds=45),
        ),
        now=NOW,
    )
    codes = {item.code for item in findings}
    assert "TARGET_NOT_REACHED" in codes
    assert "PENDING_TRANSITION_STUCK" in codes
    assert "EXECUTION_REQUEST_STUCK" in codes


def test_autotrade_off_suppresses_strategy_contract_findings() -> None:
    findings = evaluate_watchdog_contracts_v1(
        _snapshot(
            observed_direction="SHORT",
            intent_signal_at=NOW - timedelta(minutes=5),
            auto_manage_enabled=False,
        ),
        now=NOW,
    )
    assert findings == ()


def test_watchdog_has_no_execution_authority() -> None:
    source = Path("autotrader_runtime_watchdog_v1.py").read_text(encoding="utf-8").lower()
    for forbidden in (
        "trade/v2/orders",
        "session.post(",
        "requests.post(",
        "place_order(",
        "run_live_open_once",
        "run_live_close_once",
        "set_auto_manage_enabled",
    ):
        assert forbidden not in source


def test_stream_worker_starts_watchdog_and_runtime_page_exposes_shareable_report() -> None:
    worker = Path("realtime_worker.py").read_text(encoding="utf-8")
    page = Path("pages/99_Runtime_Diagnostics.py").read_text(encoding="utf-8")

    assert "run_runtime_watchdog_forever_v1" in worker
    assert "PRICEGAUGER_AUTOTRADER_WATCHDOG_SECONDS" in worker
    assert "pricegauger-autotrader-runtime-watchdog" in worker
    assert "load_watchdog_report_by_id_v1" in page
    assert 'st.query_params["watchdog_report"]' in page
    assert "format_watchdog_report_v1" in page
