"""Read-only AutoTrader watcher wiring tests; no Saxo broker access."""
import inspect
from autotrader_account_learning_v1 import auto_active_v3_learning_accounts
import autotrader_account_learning_v1 as learning
from autotrader_v3_fleet_observer_v1 import assess
import worker


def test_worker_cycle_attaches_readonly_fleet_monitor():
    code=inspect.getsource(worker.run_once)
    assert "run_monitor_once(db_path=str(db_path))" in code
    assert "except Exception" in code


def test_five_minute_learning_includes_active_accounts(monkeypatch,tmp_path):
    path=str(tmp_path/"pg.sqlite3")
    monkeypatch.setattr(learning,"auto_active_v3_learning_accounts",
                        lambda **k:("armed-account",))
    monkeypatch.setattr(learning,"load_account_truth_v1",lambda **k:())
    observed=learning.run_account_learning_cycle_v1(db_path=path)
    assert observed["watched_accounts"]==1
    assert observed["errors"]==0


def test_observer_does_not_hide_unresolved_order():
    from datetime import datetime,timedelta,timezone
    now=datetime(2026,10,27,tzinfo=timezone.utc)
    severity,reason=assess(
        now=now,status="RUNNING",updated_at=now.isoformat(),
        pending="UNKNOWN",
        pending_at=(now-timedelta(minutes=4)).isoformat(),fills=0)
    assert severity=="CRITICAL"
    assert "UNRESOLVED_ORDER" in reason
