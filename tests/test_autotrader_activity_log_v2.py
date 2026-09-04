from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import autotrader_activity_log_v2 as activity_v2
from autotrader_activity_log_v2 import build_automanager_lifecycle_status_v2
from autotrader_strategy_catalog_v2 import MACD_LONG_FLAT_STRATEGY_V2
from autotrader_strategy_enrollment_v2 import (
    ENTRY_MODE_AUTO,
    StrategyEnrollmentV2,
)

NOW = datetime(2026, 8, 31, 9, 0, tzinfo=timezone.utc)


def _enrollment(**changes) -> StrategyEnrollmentV2:
    item = StrategyEnrollmentV2(
        pilot_key="pilot-tech100",
        strategy_key=MACD_LONG_FLAT_STRATEGY_V2,
        execution_mode="LIVE_MANAGE",
        account_id="account",
        anchor_net_position_id="position",
        uic=4912,
        asset_type="CfdOnIndex",
        market_id=7,
        instrument_id=11,
        market_name="US Tech 100 NAS · Saxo 4912",
        enabled=True,
        live_open_armed=True,
        entry_mode=ENTRY_MODE_AUTO,
    )
    return replace(item, **changes)


def test_long_pilot_explains_the_next_bearish_exit_signal() -> None:
    status, next_step = build_automanager_lifecycle_status_v2(
        _enrollment(),
        observed_direction="LONG",
    )

    assert status == "LONG · pilot aktiv"
    assert "bearish signal" in next_step
    assert "mål FLAT" in next_step


def test_strategy_flat_is_not_presented_as_a_stopped_pilot() -> None:
    status, next_step = build_automanager_lifecycle_status_v2(
        _enrollment(),
        observed_direction="FLAT",
        latest_strategy_close_signal="CROSS_DOWN",
        latest_strategy_close_at=NOW,
    )

    assert status == "FLAT pga. bearish strategisignal"
    assert "automatisk OPEN/re-entry er aktiv" in next_step
    assert "bullish signal" in next_step


def test_guardian_provenance_wins_when_its_close_is_newer() -> None:
    status, next_step = build_automanager_lifecycle_status_v2(
        _enrollment(),
        observed_direction="FLAT",
        latest_strategy_close_signal="CROSS_DOWN",
        latest_strategy_close_at=NOW - timedelta(hours=1),
        latest_guardian_reason="TRAILING_STOP",
        latest_guardian_close_at=NOW,
    )

    assert status == "FLAT etter Position Guardian · Trailing stop"
    assert "bullish signal" in next_step


def test_disabled_enrollment_is_explicitly_finished() -> None:
    status, next_step = build_automanager_lifecycle_status_v2(
        _enrollment(enabled=False),
        observed_direction="FLAT",
    )

    assert status == "Pilot avsluttet"
    assert "aktiveres på nytt" in next_step


def test_inflight_close_takes_precedence_over_observed_position() -> None:
    status, next_step = build_automanager_lifecycle_status_v2(
        _enrollment(),
        observed_direction="LONG",
        pending_action="CLOSE",
        pending_status="ORDER_ACCEPTED",
    )

    assert status == "CLOSE under behandling"
    assert next_step == "Ordre akseptert · venter på avstemming"


def test_open_position_without_exact_management_basis_is_auto_registered() -> None:
    status, next_step = build_automanager_lifecycle_status_v2(
        _enrollment(),
        observed_direction="LONG",
        exact_close_authority=False,
    )

    assert status == "LONG · registrerer AutoManager-basis"
    assert "ingen brukerbekreftelse kreves" in next_step


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class _ActivityDb:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, _params):
        if "FROM pg_v2_autotrader_strategy_enrollments" in sql:
            return _Rows(((NOW - timedelta(hours=4), True),))
        if (
            "FROM pg_v2_autotrader_strategy_evaluations" in sql
            and "e.signal_at" not in sql
        ):
            return _Rows(((NOW, "FLAT"),))
        if "FROM pg_v2_autotrader_strategy_evaluations e" in sql:
            return _Rows(
                (
                    (
                        NOW - timedelta(hours=3),
                        "CROSS_DOWN",
                        "CLOSE",
                        "FLAT",
                        "LONG",
                        "RECONCILED",
                        None,
                        85.95,
                        "NOK",
                    ),
                )
            )
        if "FROM pg_v2_autotrader_execution_requests" in sql:
            return _Rows((("CLOSE", "RECONCILED", None, NOW - timedelta(hours=3)),))
        if "FROM pg_v2_autotrader_managed_positions" in sql:
            return _Rows(((NOW - timedelta(hours=2),),))
        if "FROM pg_v2_autotrader_risk_state r" in sql:
            return _Rows(())
        if "FROM pg_v2_autotrader_risk_events" in sql:
            return _Rows(())
        raise AssertionError(sql)


def test_old_close_is_kept_in_history_but_not_claimed_as_current_flat_cause(
    monkeypatch,
) -> None:
    monkeypatch.setattr(activity_v2, "connect", lambda: _ActivityDb())

    log = activity_v2.load_automanager_activity_log_v2(_enrollment())

    assert log.lifecycle_status == "FLAT · pilot aktiv"
    assert any(event.title == "Bearish kryss → CLOSE" for event in log.events)
    assert any(event.realized_net_pnl == 85.95 for event in log.events)


def test_fresh_live_authority_override_reports_auto_basis_registration(monkeypatch) -> None:
    monkeypatch.setattr(activity_v2, "connect", lambda: _ActivityDb())

    log = activity_v2.load_automanager_activity_log_v2(
        _enrollment(),
        observed_direction_override="LONG",
        exact_close_authority_override=False,
    )

    assert log.lifecycle_status == "LONG · registrerer AutoManager-basis"
    assert "ingen brukerbekreftelse kreves" in log.next_step
