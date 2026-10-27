from datetime import datetime,timedelta,timezone
from autotrader_v3_fleet_observer_v1 import assess,ensure_monitor_schema,load_monitor_rows
from database import connect


def test_read_only_observer_classifies_stale_and_pending_without_broker():
    now=datetime(2026,10,27,19,0,tzinfo=timezone.utc)
    ok=assess(now=now,status="MANAGING",updated_at=now.isoformat(),
              pending=None,pending_at=None,fills=1)
    assert ok==("OK","healthy")
    bad=assess(now=now,status="RUNNING",
               updated_at=(now-timedelta(minutes=5)).isoformat(),
               pending="UNKNOWN",pending_at=(now-timedelta(minutes=3)).isoformat(),fills=8)
    assert bad[0]=="CRITICAL"
    assert "UNRESOLVED_ORDER" in bad[1]
    assert "HIGH_TURNOVER" in bad[1]


def test_observer_schema_is_idempotent_and_empty_valid(tmp_path):
    path=str(tmp_path/"monitor.sqlite3")
    ensure_monitor_schema(path)
    ensure_monitor_schema(path)
    assert load_monitor_rows(db_path=path)==()


def test_no_saxo_import_or_trade_permission_in_monitor_module():
    import inspect
    import autotrader_v3_fleet_observer_v1 as module
    source=inspect.getsource(module)
    assert "place_order(" not in source
    assert "set_live_authority_v3(" not in source
    assert "save_autotrader_config_v3(" not in source
