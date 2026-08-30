from __future__ import annotations

from pathlib import Path

import autotrader_managed_positions_v1 as managed_v1
from autotrader_risk_control_v2 import PositionObservationV2


class _FakeDb:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple | None]] = []

    def execute(self, sql: str, params=None):
        self.calls.append((sql, params))
        return self


class _FakeConnect:
    def __init__(self, db: _FakeDb) -> None:
        self.db = db

    def __enter__(self):
        return self.db

    def __exit__(self, exc_type, exc, tb):
        return False


def _observation() -> PositionObservationV2:
    return PositionObservationV2(
        account_id="acct-1",
        net_position_id="net-1",
        uic=4912,
        asset_type="CfdOnIndex",
        direction="Buy",
        amount=0.25,
        average_open_price=29000.0,
        current_price=29372.36,
        pnl_pct=1.284,
        price_delay_minutes=0,
        can_be_closed=True,
        calculation_reliability="Ok",
        is_market_open=True,
        non_tradable_reason="None",
    )


def test_enrollment_resets_existing_risk_epoch_before_granting_managed_authority(monkeypatch):
    db = _FakeDb()
    monkeypatch.setattr(managed_v1, "connect", lambda: _FakeConnect(db))

    managed_v1.enroll_position_v1(_observation())

    assert len(db.calls) == 2
    risk_sql, risk_params = db.calls[0]
    managed_sql, _ = db.calls[1]
    assert "UPDATE pg_v2_autotrader_risk_state" in risk_sql
    assert "high_water_pct = ?" in risk_sql
    assert "trailing_floor_pct = NULL" in risk_sql
    assert "triggered_reason = NULL" in risk_sql
    assert "triggered_at = NULL" in risk_sql
    assert "last_reason = 'MANAGEMENT_ENROLLED'" in risk_sql
    assert risk_params is not None
    assert risk_params[6] == 1.284
    assert risk_params[7] == 1.284
    assert "INSERT INTO pg_v2_autotrader_managed_positions" in managed_sql


def test_management_epoch_reset_preserves_risk_event_audit_history():
    source = Path("autotrader_managed_positions_v1.py").read_text(encoding="utf-8")
    assert "DELETE FROM pg_v2_autotrader_risk_events" not in source
    assert source.index("UPDATE pg_v2_autotrader_risk_state") < source.index(
        "INSERT INTO pg_v2_autotrader_managed_positions"
    )
