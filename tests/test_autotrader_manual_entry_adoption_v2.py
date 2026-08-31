from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import autotrader_manual_entry_adoption_v2 as adoption_v2
from autotrader_risk_control_v2 import PositionObservationV2
from autotrader_strategy_enrollment_v2 import (
    ENTRY_MODE_AUTO,
    ENTRY_MODE_MANUAL_ONLY,
    EXECUTION_MODE_LIVE,
)


class _FakeResult:
    def __init__(self, db):
        self.db = db

    def fetchone(self):
        if self.db.fetchone_values:
            return self.db.fetchone_values.pop(0)
        return None


class _FakeDb:
    def __init__(self, events: list[str], fetchone_values=None):
        self.events = events
        self.fetchone_values = list(fetchone_values or [])

    def execute(self, sql: str, params=None):
        compact = " ".join(sql.split())
        self.events.append(f"sql:{compact}")
        return _FakeResult(self)


class _FakeConnect:
    def __init__(self, db: _FakeDb):
        self.db = db

    def __enter__(self):
        return self.db

    def __exit__(self, exc_type, exc, tb):
        return False


def _enrollment(*, entry_mode=ENTRY_MODE_MANUAL_ONLY, anchor="old-net"):
    return SimpleNamespace(
        pilot_key="pilot-1",
        strategy_key="macd-30m-long-flat-v1",
        execution_mode=EXECUTION_MODE_LIVE,
        account_id="acct-1",
        anchor_net_position_id=anchor,
        uic=4912,
        asset_type="CfdOnIndex",
        market_id=7,
        instrument_id=77,
        market_name="US Tech 100 NAS · Saxo 4912",
        enabled=True,
        live_open_armed=False,
        entry_mode=entry_mode,
    )


def _observation(*, net_position_id="new-net", amount=0.25, opening=29000.0):
    return PositionObservationV2(
        account_id="acct-1",
        net_position_id=net_position_id,
        uic=4912,
        asset_type="CfdOnIndex",
        direction="Buy",
        amount=amount,
        average_open_price=opening,
        current_price=29300.0,
        pnl_pct=1.0,
        price_delay_minutes=0,
        can_be_closed=True,
        calculation_reliability="Ok",
        is_market_open=True,
        non_tradable_reason="None",
    )


def test_manual_adoption_refuses_auto_entry_modes_before_any_authority_change(monkeypatch):
    monkeypatch.setattr(adoption_v2, "ensure_autotrader_schema_v2", lambda: None)
    with pytest.raises(ValueError, match="MANUAL_ENTRY_ONLY"):
        adoption_v2.adopt_manual_entry_position_v2(
            _enrollment(entry_mode=ENTRY_MODE_AUTO),
            _observation(),
        )


def test_user_confirmed_adoption_allows_auto_pilot_without_sending_an_order(monkeypatch):
    events: list[str] = []
    db = _FakeDb(events, fetchone_values=[None, None, None])
    monkeypatch.setattr(adoption_v2, "ensure_autotrader_schema_v2", lambda: None)
    monkeypatch.setattr(adoption_v2, "is_position_managed_v1", lambda _obs: False)
    monkeypatch.setattr(adoption_v2, "connect", lambda: _FakeConnect(db))
    monkeypatch.setattr(
        adoption_v2,
        "enroll_position_v1",
        lambda obs: events.append(f"enroll:{obs.net_position_id}"),
    )

    changed = adoption_v2.adopt_user_confirmed_position_v2(
        _enrollment(entry_mode=ENTRY_MODE_AUTO),
        _observation(),
    )

    assert changed is True
    assert "enroll:new-net" in events
    assert all("trade/v2/orders" not in event for event in events)


def test_exact_already_managed_basis_is_noop_but_repairs_strategy_anchor(monkeypatch):
    events: list[str] = []
    db = _FakeDb(events)
    monkeypatch.setattr(adoption_v2, "ensure_autotrader_schema_v2", lambda: None)
    monkeypatch.setattr(adoption_v2, "is_position_managed_v1", lambda _obs: True)
    monkeypatch.setattr(adoption_v2, "connect", lambda: _FakeConnect(db))
    monkeypatch.setattr(
        adoption_v2,
        "enroll_position_v1",
        lambda _obs: events.append("enroll"),
    )

    changed = adoption_v2.adopt_manual_entry_position_v2(
        _enrollment(anchor="stale-anchor"),
        _observation(net_position_id="new-net"),
    )

    assert changed is False
    assert "enroll" not in events
    assert any("UPDATE pg_v2_autotrader_strategy_enrollments" in event for event in events)


def test_unresolved_pricegauger_execution_request_blocks_manual_adoption(monkeypatch):
    events: list[str] = []
    db = _FakeDb(events, fetchone_values=[{"request_id": "inflight"}])
    monkeypatch.setattr(adoption_v2, "ensure_autotrader_schema_v2", lambda: None)
    monkeypatch.setattr(adoption_v2, "is_position_managed_v1", lambda _obs: False)
    monkeypatch.setattr(adoption_v2, "connect", lambda: _FakeConnect(db))
    monkeypatch.setattr(
        adoption_v2,
        "enroll_position_v1",
        lambda _obs: events.append("enroll"),
    )

    with pytest.raises(RuntimeError, match="execution is unresolved"):
        adoption_v2.adopt_manual_entry_position_v2(_enrollment(), _observation())

    assert "enroll" not in events
    assert not any("UPDATE pg_v2_autotrader_managed_positions" in event for event in events)


def test_unresolved_live_close_attempt_also_blocks_basis_rotation(monkeypatch):
    events: list[str] = []
    db = _FakeDb(events, fetchone_values=[None, None, {"event_id": "close-inflight"}])
    monkeypatch.setattr(adoption_v2, "ensure_autotrader_schema_v2", lambda: None)
    monkeypatch.setattr(adoption_v2, "is_position_managed_v1", lambda _obs: False)
    monkeypatch.setattr(adoption_v2, "connect", lambda: _FakeConnect(db))
    monkeypatch.setattr(
        adoption_v2,
        "enroll_position_v1",
        lambda _obs: events.append("enroll"),
    )

    with pytest.raises(RuntimeError, match="execution is unresolved"):
        adoption_v2.adopt_manual_entry_position_v2(_enrollment(), _observation())

    assert "enroll" not in events
    assert any("FROM pg_v2_autotrader_live_close_attempts" in event for event in events)


def test_new_manual_basis_supersedes_stale_authority_then_uses_risk_epoch_enrollment(monkeypatch):
    events: list[str] = []
    # Execution-request, LIVE OPEN and LIVE CLOSE unresolved checks are all clear.
    db = _FakeDb(events, fetchone_values=[None, None, None])
    monkeypatch.setattr(adoption_v2, "ensure_autotrader_schema_v2", lambda: None)
    monkeypatch.setattr(adoption_v2, "is_position_managed_v1", lambda _obs: False)
    monkeypatch.setattr(adoption_v2, "connect", lambda: _FakeConnect(db))
    monkeypatch.setattr(
        adoption_v2,
        "enroll_position_v1",
        lambda obs: events.append(f"enroll:{obs.net_position_id}"),
    )

    changed = adoption_v2.adopt_manual_entry_position_v2(_enrollment(), _observation())

    assert changed is True
    supersede = next(i for i, event in enumerate(events) if "UPDATE pg_v2_autotrader_execution_requests" in event)
    clear_intent = next(i for i, event in enumerate(events) if "UPDATE pg_v2_autotrader_strategy_runtime_state" in event)
    retire = next(i for i, event in enumerate(events) if "UPDATE pg_v2_autotrader_managed_positions" in event)
    enroll = events.index("enroll:new-net")
    anchor = next(i for i, event in enumerate(events) if "UPDATE pg_v2_autotrader_strategy_enrollments" in event)
    assert supersede < clear_intent < retire < enroll < anchor
    assert "status IN (?, ?)" in events[supersede]
    assert "MANUAL_POSITION_ADOPTED" in events[supersede]


def test_adoption_cycle_only_considers_active_manual_live_pilots(monkeypatch):
    manual = _enrollment()
    auto = _enrollment(entry_mode=ENTRY_MODE_AUTO)
    auto.pilot_key = "pilot-auto"
    monkeypatch.setattr(adoption_v2, "using_postgres", lambda: True)
    monkeypatch.setattr(adoption_v2, "ensure_autotrader_schema_v2", lambda: None)
    monkeypatch.setattr(
        adoption_v2,
        "load_active_strategy_enrollments_v2",
        lambda: (manual, auto),
    )
    monkeypatch.setattr(adoption_v2, "configured_client", lambda: object())
    monkeypatch.setattr(adoption_v2, "_position_observations_v2", lambda _client: (_observation(),))
    adopted = []
    monkeypatch.setattr(
        adoption_v2,
        "adopt_manual_entry_position_v2",
        lambda enrollment, _obs: adopted.append(enrollment.pilot_key) or True,
    )

    summary = adoption_v2.run_manual_entry_adoption_cycle_v2()

    assert adopted == ["pilot-1"]
    assert summary.candidates == 1
    assert summary.adopted == 1
    assert summary.failed == 0


def test_manual_adoption_has_no_open_order_or_product_admission_authority():
    source = Path("autotrader_manual_entry_adoption_v2.py").read_text(encoding="utf-8")
    assert "session.post" not in source
    assert "_post_once" not in source
    assert "save_product_admission" not in source
    assert "MarginEnvelope" not in source
    assert "CREATE TABLE" not in source


def test_strategy_close_daemon_adopts_manual_basis_before_close_execution():
    source = Path("autotrader_strategy_live_close_v2.py").read_text(encoding="utf-8")
    adoption_call = source.index("adoption = run_manual_entry_adoption_cycle_v2()")
    close_call = source.index("run_strategy_live_close_cycle_v2()", adoption_call)
    assert adoption_call < close_call
