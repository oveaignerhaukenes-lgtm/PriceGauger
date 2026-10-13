"""Read-only diagnostics must never interfere with PAPER collection or LIVE."""
from __future__ import annotations
from datetime import datetime,timezone
import json
import logging
from unittest.mock import Mock

import live_sim_lab_worker_v1 as worker
import live_sim_lab_store_v1 as store


def test_sim_audit_emits_real_snapshot_fields_without_strategy_mutations(monkeypatch,caplog):
    row=dict(experiment_id="e1",market_name="US Tech 100 NAS",
             family="sticky",signal_tf=5,regime_tf=30,modifier="whipsaw_pause",
             max_exposure=0.5,started_at="2026-10-09T00:00:00Z",status="ACTIVE",
             observed_bars=500,last_bar="2026-10-13T12:40:00Z",
             return_pct=1.15,max_drawdown_pct=0.4,trades=8,
             above_start_pct=70.0,positive_bar_pct=50.0,exposure=0.5)
    monkeypatch.setattr(store,"lab_snapshot",lambda **kwargs:([row],[],[]))
    def no_extra(_name):
        raise RuntimeError("not available")
    import importlib
    monkeypatch.setattr(importlib,"import_module",no_extra)
    with caplog.at_level(logging.INFO,logger="pricegauger.live_sim_lab"):
        worker.emit_sim_performance_audit_v1(db_path="test.db")
    reports=[x.message for x in caplog.records if x.message.startswith("SIM_AUDIT_VARIANT ")]
    assert len(reports)==1
    parsed=json.loads(reports[0].split(" ",1)[1])
    assert parsed["return_pct"]==1.15
    assert parsed["observed_bars"]==500
    assert parsed["max_drawdown_pct"]==0.4
    assert parsed["trades"]==8
    assert "SIM_AUDIT_META " in caplog.text


def test_sim_audit_only_once_even_after_multiple_market_cycles(monkeypatch):
    monkeypatch.setattr(worker,"_SIM_AUDIT_EMITTED",False)
    monkeypatch.setattr(worker,"refresh_macro_schedule",lambda **kw:"UNCHANGED")
    monkeypatch.setattr(worker,"process_lab_cycle",lambda **kw:1)
    audit=Mock()
    monkeypatch.setattr(worker,"emit_sim_performance_audit_v1",audit)
    now=datetime(2026,10,13,11,0,tzinfo=timezone.utc)
    assert worker.run_once(now=now)==1
    assert worker.run_once(now=now)==1
    assert audit.call_count==1
