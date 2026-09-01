from __future__ import annotations

from datetime import datetime, timezone

import pytest

import autotrader_strategy_switch_provenance_v2 as module
from autotrader_strategy_enrollment_v2 import EXECUTION_MODE_LIVE, StrategyEnrollmentV2


NOW = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)


class _Cursor:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class _Db:
    def __init__(self, *, unresolved=None, settled=None, handoff=None, consumed=None):
        self.unresolved = unresolved
        self.settled = settled
        self.handoff = handoff
        self.consumed = consumed

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=()):
        normalized = " ".join(str(sql).split())
        if "SELECT enrolled_at FROM pg_v2_autotrader_strategy_enrollments" in normalized:
            return _Cursor({"enrolled_at": NOW})
        if "LEFT JOIN pg_v2_autotrader_equity_reconciliations" in normalized:
            return _Cursor(self.unresolved)
        if "JOIN pg_v2_autotrader_equity_reconciliations" in normalized:
            return _Cursor(self.settled)
        if "FROM pg_v2_autotrader_strategy_switch_events" in normalized:
            return _Cursor(self.handoff)
        if "FROM pg_v2_autotrader_execution_requests" in normalized:
            return _Cursor(self.consumed)
        raise AssertionError(normalized)


def _enrollment(anchor: str = "old-net-position") -> StrategyEnrollmentV2:
    return StrategyEnrollmentV2(
        pilot_key="source-pilot",
        strategy_key="macd-30m-long-flat-v1",
        execution_mode=EXECUTION_MODE_LIVE,
        account_id="acct",
        anchor_net_position_id=anchor,
        uic=4912,
        asset_type="CfdOnIndex",
        market_id=1,
        instrument_id=2,
        market_name="US Tech 100 NAS · Saxo 4912",
        enabled=True,
        live_open_armed=False,
        entry_mode="AUTO",
    )


def _patch(monkeypatch, db: _Db) -> None:
    monkeypatch.setattr(module, "ensure_strategy_switch_provenance_schema_v2", lambda: None)
    monkeypatch.setattr(module, "connect", lambda: db)


def test_source_unresolved_close_blocks_strategy_handoff(monkeypatch) -> None:
    _patch(monkeypatch, _Db(unresolved={"event_id": "u"}))
    with pytest.raises(ValueError, match="unresolved close/P&L"):
        module.require_source_settled_flat_provenance_v2(_enrollment())


def test_source_reconciled_close_authorizes_strategy_handoff(monkeypatch) -> None:
    _patch(monkeypatch, _Db(settled={"event_id": "11111111-1111-1111-1111-111111111111"}))
    result = module.require_source_settled_flat_provenance_v2(_enrollment())
    assert result.kind == "SETTLED_PG_CLOSE"
    assert result.source_close_event_id == "11111111-1111-1111-1111-111111111111"


def test_source_exposure_history_without_settled_close_is_rejected(monkeypatch) -> None:
    _patch(monkeypatch, _Db())
    with pytest.raises(ValueError, match="exposure history without a settled PG close"):
        module.require_source_settled_flat_provenance_v2(_enrollment())


def test_never_exposed_source_can_handoff_confirmed_flat(monkeypatch) -> None:
    _patch(monkeypatch, _Db())
    result = module.require_source_settled_flat_provenance_v2(_enrollment(anchor=""))
    assert result.kind == "NO_SOURCE_EXPOSURE"
    assert result.source_close_event_id is None


def test_target_flat_handoff_is_available_until_first_submit(monkeypatch) -> None:
    handoff = {"event_id": "switch", "created_at": NOW}
    _patch(monkeypatch, _Db(handoff=handoff, consumed=None))
    assert module.has_unconsumed_settled_flat_handoff_v2(
        pilot_key="target-pilot",
        enrolled_at=NOW,
    ) is True

    _patch(monkeypatch, _Db(handoff=handoff, consumed={"exists": 1}))
    assert module.has_unconsumed_settled_flat_handoff_v2(
        pilot_key="target-pilot",
        enrolled_at=NOW,
    ) is False
