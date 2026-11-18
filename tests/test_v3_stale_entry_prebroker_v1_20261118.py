"""Expired impulse entries must not consume Saxo cost/precheck quota."""
from pathlib import Path

import autotrader_v3_live_runtime_v1 as runtime


def test_v3_quote_entry_expiry_precedes_cost_precheck_and_post():
    src=Path("autotrader_v3_live_runtime_v1.py").read_text()
    i=src.index("Quote impulse expired before Saxo cost/precheck")
    gate=src.rfind("if not _fresh_quote_open_authorized_v3(",0,i)
    cost=src.index("cost_assessment=assess_transaction_cost_v3(",i)
    precheck=src.index("pre=broker.precheck(order)",cost)
    submit=src.index("result=broker.place_order(order,confirm_live=True)",precheck)
    assert gate<i<cost<precheck<submit
    # Preserve both downstream checks for a signal aging during cost/precheck.
    assert src.count("if mutation.action in {'OPEN','ADD'} and not _fresh_quote_open_authorized_v3(")>=2
    assert "if mutation.action in {'REDUCE','CLOSE'}:" in src[:gate]
    assert "if mutation.action in {'OPEN','ADD'}:\n            # Reject" in src[:gate+100]


def test_stale_tick_signal_rejected_without_broker_access(tmp_path):
    from datetime import datetime, timedelta, timezone
    import sqlite3

    db=str(tmp_path/"stale.db")
    clock=datetime(2026,11,18,20,0,0,tzinfo=timezone.utc)
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE pg_v3_tick_live_state (trader_id TEXT PRIMARY KEY,last_signal_at TEXT)")
        conn.execute("INSERT INTO pg_v3_tick_live_state VALUES (?,?)", (
            "test-trader",(clock-timedelta(seconds=7)).isoformat()))
    signal=(clock-timedelta(seconds=7)).isoformat()
    assert not runtime._fresh_quote_open_authorized_v3(
        strategy_key="impulse-catcher-long-tick-v1-1",
        decision_key=f"tick:impulse-catcher-long-v1-1:{signal}:TICK_LONG",
        trader_id="test-trader",db_path=db,clock=clock)
