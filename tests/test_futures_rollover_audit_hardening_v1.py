from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import datetime, timezone
from pathlib import Path

import pytest

import futures_rollover_schema_v1 as schema_module
import futures_rollover_v1 as rollover_module
import runtime_subscription_bridge_v2 as runtime_module
from instrument_registry_v2 import InstrumentSourceV2
from saxo_provider import SaxoInstrument


def _source() -> InstrumentSourceV2:
    return InstrumentSourceV2(
        market_id=7,
        market_name="Brent",
        instrument_id=41,
        instrument_type="future",
        display_name="Brent Sep 2026",
        provider="saxo",
        provider_instrument_id="43660942",
        asset_type="ContractFutures",
        symbol="COU6",
        price_multiplier=1.0,
        metadata={"expiry": "2026-08-28T18:30:00Z"},
    )


class _Cursor:
    rowcount = 1


class _RecordingDb:
    is_postgres = True

    def __init__(self, *, fail_on_audit: bool = False) -> None:
        self.fail_on_audit = fail_on_audit
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, sql: str, parameters=()):
        compact = " ".join(str(sql).split())
        values = tuple(parameters or ())
        self.calls.append((compact, values))
        if self.fail_on_audit and "INSERT INTO pg_v2_instrument_rollovers" in compact:
            raise RuntimeError("audit unavailable")
        return _Cursor()


class _ConnectionContext(AbstractContextManager):
    def __init__(self, db: _RecordingDb, exits: list[type[BaseException] | None]) -> None:
        self.db = db
        self.exits = exits

    def __enter__(self):
        return self.db

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self.exits.append(exc_type)
        return False


def test_collection_switch_and_audit_use_one_database_transaction(monkeypatch) -> None:
    db = _RecordingDb()
    exits: list[type[BaseException] | None] = []
    connect_calls = 0

    def _connect():
        nonlocal connect_calls
        connect_calls += 1
        return _ConnectionContext(db, exits)

    monkeypatch.setattr(rollover_module, "connect", _connect)
    rollover_module._commit_collection_rollover_v1(
        source=_source(),
        new_instrument_id=52,
        candidate=SaxoInstrument(asset="Brent", uic=44297299, asset_type="ContractFutures"),
        old_symbol="COU6",
        new_symbol="COV6",
        occurred_at=datetime(2026, 9, 6, 20, 51, tzinfo=timezone.utc),
        reason="CURRENT_EXPIRED",
        metadata={"selection": "SAXO_PRIMARY_LISTING_OR_FUTURES_SPACE"},
    )

    assert connect_calls == 1
    assert exits == [None]
    statements = [sql for sql, _params in db.calls]
    assert sum("pg_v2_collection_subscriptions" in sql for sql in statements) == 2
    assert sum("pg_v2_instrument_rollovers" in sql for sql in statements) == 1
    assert "enabled = FALSE" in statements[0]
    assert "enabled = TRUE" in statements[1]


def test_audit_failure_leaves_transaction_context_on_rollback_path(monkeypatch) -> None:
    db = _RecordingDb(fail_on_audit=True)
    exits: list[type[BaseException] | None] = []
    monkeypatch.setattr(rollover_module, "connect", lambda: _ConnectionContext(db, exits))

    with pytest.raises(RuntimeError, match="audit unavailable"):
        rollover_module._commit_collection_rollover_v1(
            source=_source(),
            new_instrument_id=52,
            candidate=SaxoInstrument(asset="Brent", uic=44297299, asset_type="ContractFutures"),
            old_symbol="COU6",
            new_symbol="COV6",
            occurred_at=datetime(2026, 9, 6, 20, 51, tzinfo=timezone.utc),
            reason="CURRENT_EXPIRED",
            metadata={},
        )

    assert exits == [RuntimeError]
    assert len(db.calls) == 3


def test_rollover_rejects_same_immutable_instrument_identity(monkeypatch) -> None:
    monkeypatch.setattr(
        rollover_module,
        "connect",
        lambda: (_ for _ in ()).throw(AssertionError("database must not be touched")),
    )
    with pytest.raises(ValueError, match="distinct immutable instrument identity"):
        rollover_module._commit_collection_rollover_v1(
            source=_source(),
            new_instrument_id=41,
            candidate=SaxoInstrument(asset="Brent", uic=44297299, asset_type="ContractFutures"),
            old_symbol="COU6",
            new_symbol="COV6",
            occurred_at=datetime(2026, 9, 6, 20, 51, tzinfo=timezone.utc),
            reason="CURRENT_EXPIRED",
            metadata={},
        )


def test_audit_schema_is_prepared_before_runtime_resolver(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(runtime_module, "_discover_open_positions_best_effort", lambda: calls.append("discover"))
    monkeypatch.setattr(
        runtime_module,
        "ensure_futures_rollover_audit_ready_v1",
        lambda: calls.append("audit") or 0,
    )
    monkeypatch.setattr(runtime_module, "resolve_saxo_futures_rollovers_once_v1", lambda: calls.append("roll") or type("S", (), {"rolled": 0, "failed": 0})())
    monkeypatch.setattr(runtime_module, "_seed_discovered_history_best_effort", lambda: calls.append("seed"))
    monkeypatch.setattr(runtime_module, "list_subscribed_sources_v2", lambda provider=None: ())

    runtime_module.load_runtime_instruments_v2({})
    assert calls == ["discover", "audit", "roll", "seed"]


def test_audit_preparation_failure_blocks_rollover(monkeypatch) -> None:
    monkeypatch.setattr(
        runtime_module,
        "ensure_futures_rollover_audit_ready_v1",
        lambda: (_ for _ in ()).throw(RuntimeError("schema down")),
    )
    with pytest.raises(RuntimeError, match="audit preparation failed"):
        runtime_module._prepare_futures_rollover_audit_best_effort()


def test_schema_recovery_contract_is_idempotent_and_uses_source_creation_time() -> None:
    source = Path("futures_rollover_schema_v1.py").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS pg_v2_instrument_rollovers" in source
    assert "ON CONFLICT (provider, old_provider_instrument_id, new_provider_instrument_id)" in source
    assert "rollover_from_uic" in source
    assert "SELECT created_at" in source
    assert '"recovered_audit": True' in source


def test_rollover_module_contains_no_execution_authority() -> None:
    source = Path("futures_rollover_v1.py").read_text(encoding="utf-8")
    assert "set_collection_subscription_v2" not in source
    for forbidden in ("place_order", "submit_order", "autotrader_live_open", "autotrader_live_close"):
        assert forbidden not in source
