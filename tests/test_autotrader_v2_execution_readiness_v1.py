from types import SimpleNamespace

import autotrader_v2_execution_readiness_v1 as readiness


def _enrollment():
    return SimpleNamespace(pilot_key="pilot-v2", account_id="lager", uic=4912, asset_type="CfdOnIndex")


def test_ready_only_for_exact_v2_owner(monkeypatch):
    monkeypatch.setattr(readiness, "load_account_owner_v1", lambda account_id, db_path: SimpleNamespace(engine_id="V2", owner_key="pilot-v2"))
    state = readiness.execution_readiness_v2_vnext_v1(_enrollment())
    assert state.ready is True
    assert state.status == "READY"


def test_v3_owned_account_is_blocked(monkeypatch):
    monkeypatch.setattr(readiness, "load_account_owner_v1", lambda account_id, db_path: SimpleNamespace(engine_id="V3", owner_key="pilot-v3"))
    state = readiness.execution_readiness_v2_vnext_v1(_enrollment())
    assert state.ready is False
    assert state.status == "BLOCKED"
    assert "V3" in state.detail


def test_other_v2_runtime_is_blocked(monkeypatch):
    monkeypatch.setattr(readiness, "load_account_owner_v1", lambda account_id, db_path: SimpleNamespace(engine_id="V2", owner_key="other-pilot"))
    state = readiness.execution_readiness_v2_vnext_v1(_enrollment())
    assert state.ready is False
    assert "different V2 runtime" in state.detail


def test_unowned_account_is_blocked(monkeypatch):
    monkeypatch.setattr(readiness, "load_account_owner_v1", lambda account_id, db_path: None)
    assert readiness.execution_readiness_v2_vnext_v1(_enrollment()).ready is False
