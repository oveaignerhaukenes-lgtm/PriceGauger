from pathlib import Path

import pytest

import autotrader_v3_live_runtime_v1 as runtime
from database import connect


@pytest.mark.parametrize(
    ("label","minutes"),
    [
        ("1m",1),
        ("2m",2),
        ("5m",5),
        ("10m",10),
        ("15m",15),
        ("30m",30),
        ("1h",60),
    ],
)
def test_v3_live_fixed_timeframes_map_to_selected_minutes(label,minutes):
    assert runtime._live_timeframe_minutes_v3(label)==minutes


def test_v3_live_adaptive_timeframe_fails_closed_until_implemented():
    with pytest.raises(ValueError,match="Adaptiv timeframe is not implemented"):
        runtime._live_timeframe_minutes_v3("Adaptiv")


def test_context_change_clears_old_target_to_actual_and_preserves_clock(tmp_path):
    db=str(tmp_path/"v3.db")
    runtime.ensure_closed_bar_driver_schema_v3(db)
    with connect(db) as conn:
        conn.execute(
            """INSERT INTO autotrader_v3_closed_bar_state(
              trader_id,last_bar_time,target_amount,previous_spread,updated_at)
              VALUES(?,?,?,?,CURRENT_TIMESTAMP)""",
            ("pilot","2026-10-06T17:00:00+00:00",0.03,12.5),
        )

    changed=runtime._prepare_live_decision_context_v3(
        trader_id="pilot",strategy_key="macd-trailing-v1",
        timeframe_minutes=15,actual_amount=-0.01,db_path=db)

    assert changed is True
    with connect(db) as conn:
        state=conn.execute(
            "SELECT last_bar_time,target_amount,previous_spread FROM autotrader_v3_closed_bar_state WHERE trader_id=?",
            ("pilot",),
        ).fetchone()
        context=conn.execute(
            "SELECT strategy_key,timeframe_minutes FROM autotrader_v3_live_decision_context WHERE trader_id=?",
            ("pilot",),
        ).fetchone()
    get=lambda row,key,index: row[key] if isinstance(row,dict) else row[index]
    assert get(state,"last_bar_time",0)=="2026-10-06T17:00:00+00:00"
    assert float(get(state,"target_amount",1))==pytest.approx(-0.01)
    assert get(state,"previous_spread",2) is None
    assert get(context,"strategy_key",0)=="macd-trailing-v1"
    assert int(get(context,"timeframe_minutes",1))==15

    assert runtime._prepare_live_decision_context_v3(
        trader_id="pilot",strategy_key="macd-trailing-v1",
        timeframe_minutes=15,actual_amount=0.07,db_path=db) is False
    # Same context does not continuously overwrite the strategy's own target.
    with connect(db) as conn:
        unchanged=conn.execute(
            "SELECT target_amount FROM autotrader_v3_closed_bar_state WHERE trader_id=?",
            ("pilot",),
        ).fetchone()
    assert float(get(unchanged,"target_amount",0))==pytest.approx(-0.01)


def test_v3_live_runtime_routes_selected_config_timeframe_to_macd():
    source=Path("autotrader_v3_live_runtime_v1.py").read_text(encoding="utf-8")
    config=source.index("config=load_autotrader_config_v3(e.pilot_key")
    resolve=source.index("timeframe_minutes=_live_timeframe_minutes_v3(config.timeframe)",config)
    closed=source.index("closed=closed_bars_v2(",resolve)
    observation=source.index("obs=macd_observations_v2(",closed)
    assert config < resolve < closed < observation
    assert "timeframe_minutes=timeframe_minutes" in source[closed:observation+200]
    old_window=source[source.index("actual=_actual(e,broker)"):source.index("decision=evaluate_strategy_bar_v3(")]
    assert "timeframe_minutes=5" not in old_window


def test_strategy_change_discards_stale_desired_target_without_replaying_clock(tmp_path):
    db=str(tmp_path/"v3-strategy-change.db")
    runtime.ensure_closed_bar_driver_schema_v3(db)
    with connect(db) as conn:
        conn.execute(
            """INSERT INTO autotrader_v3_closed_bar_state(
              trader_id,last_bar_time,target_amount,previous_spread,updated_at)
              VALUES(?,?,?,?,CURRENT_TIMESTAMP)""",
            ("pilot","2026-10-08T22:50:00+00:00",0.10,4.2),
        )
        conn.execute(
            """CREATE TABLE autotrader_v3_live_decision_context(
              trader_id TEXT PRIMARY KEY,strategy_key TEXT NOT NULL,
              timeframe_minutes INTEGER NOT NULL,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"""
        )
        conn.execute(
            "INSERT INTO autotrader_v3_live_decision_context(trader_id,strategy_key,timeframe_minutes) VALUES(?,?,?)",
            ("pilot","old-strategy",2),
        )

    assert runtime._prepare_live_decision_context_v3(
        trader_id="pilot",strategy_key="aen21-sticky-fast-exit-v1:R15m",
        timeframe_minutes=2,actual_amount=0.0,db_path=db,
    ) is True

    with connect(db) as conn:
        state=conn.execute(
            "SELECT last_bar_time,target_amount,previous_spread FROM autotrader_v3_closed_bar_state WHERE trader_id=?",
            ("pilot",),
        ).fetchone()
    get=lambda row,key,index: row[key] if isinstance(row,dict) else row[index]
    assert get(state,"last_bar_time",0)=="2026-10-08T22:50:00+00:00"
    assert float(get(state,"target_amount",1))==0.0
    assert get(state,"previous_spread",2) is None
