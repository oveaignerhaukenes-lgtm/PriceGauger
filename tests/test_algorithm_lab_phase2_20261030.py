"""Algorithm Lab phase 2: owner ACL, causal context, funding and sandbox safety."""
from __future__ import annotations

from datetime import datetime,timedelta,timezone
from types import SimpleNamespace

import pytest

from algorithm_lab_v1 import PRESETS, LabCosts, replay_algorithm
from algorithm_lab_ticks_v1 import replay_tick_impulses
from algorithm_lab_catalog_v2 import catalog_manifest, catalog_context, catalog_asof_macro_flags
from algorithm_lab_versions_v2 import (
    new_research_key,save_experiment,list_experiments,load_experiment,
)
from algorithm_lab_sandbox_v2 import (
    standalone_worker_ready, build_docker_command, validate_script,
    execute_in_isolated_container,
)
from algorithm_lab_python_replay_v2 import replay_directions
from algorithm_lab_python_ai_v2 import DEFAULT_CODE
from database import connect

START = datetime(2026,10,1,tzinfo=timezone.utc)


def make_bars(n=1300, *, side=1):
    return [SimpleNamespace(
        bar_time=START+timedelta(minutes=i),
        open=10000+side*10*i,
        high=10000+side*10*i+12,
        low=10000+side*10*i-12,
        close=10000+side*10*i+side*5,
    ) for i in range(n)]


def test_financing_scenario_is_charged_in_model():
    bars=make_bars()
    kwargs=dict(plan=PRESETS["Trend Long / Flat"],bars=bars,
                start_at=START,end_at=START+timedelta(minutes=1300))
    base=replay_algorithm(costs=LabCosts(point_value_nok=1,spread_bps=0,
                          slippage_bps=0),**kwargs)
    funded=replay_algorithm(costs=LabCosts(point_value_nok=1,spread_bps=0,
                           slippage_bps=0,financing_long_annual_pct=20),**kwargs)
    assert base.trades and funded.trades
    assert funded.financing_nok>0
    assert funded.pnl_nok<base.pnl_nok


def test_news_and_macro_asof_catalog_do_not_leak_future(tmp_path):
    db=str(tmp_path/"context.db")
    with connect(db) as con:
        con.execute("""CREATE TABLE lsim_ctx_macro_events(
             event_id TEXT PRIMARY KEY,scheduled_at TEXT,seen_at TEXT,
             event_type TEXT,importance TEXT,source TEXT,source_url TEXT)""")
        con.execute("""INSERT INTO lsim_ctx_macro_events VALUES(?,?,?,?,?,?,?)""",
                    ("old",START.isoformat(),START.isoformat(),"US_CPI","HIGH","official","https://example.com"))
        con.execute("""INSERT INTO lsim_ctx_macro_events VALUES(?,?,?,?,?,?,?)""",
                    ("future",START.isoformat(),(START+timedelta(hours=2)).isoformat(),
                     "FOMC_DECISION","HIGH","official","https://example.com"))
        con.execute("""CREATE TABLE news_context_snapshots(
            as_of TEXT, recorded_at TEXT,source_channel TEXT,
            source_post_count INTEGER,coverage_end TEXT)""")
        con.execute("""INSERT INTO news_context_snapshots VALUES(?,?,?,?,?)""",
                    (START.isoformat(),START.isoformat(),"public",2,START.isoformat()))
        con.execute("""INSERT INTO news_context_snapshots VALUES(?,?,?,?,?)""",
                    (START.isoformat(),(START+timedelta(hours=3)).isoformat(),
                     "future-update",8,START.isoformat()))
    macro=catalog_context(dataset="macro_schedule",as_of=START+timedelta(hours=1),db_path=db)
    news=catalog_context(dataset="news_context",as_of=START+timedelta(hours=1),db_path=db)
    assert [e["event_id"] for e in macro.rows] == ["old"]
    assert [e["source_channel"] for e in news.rows] == ["public"]
    assert any(e["key"] == "accounts" and e["max_rows"] == 0 for e in catalog_manifest())
    with pytest.raises(ValueError):
        catalog_context(dataset="accounts",as_of=START,db_path=db)
    flags=catalog_asof_macro_flags(bar_times=[START-timedelta(seconds=1),START+timedelta(minutes=1)],events=macro.rows)
    assert flags[0]["observed_events"]==0
    assert flags[1]["observed_events"]==1


def test_experiments_are_immutable_and_owner_scoped(tmp_path):
    db=str(tmp_path/"versions.db")
    owner,other=new_research_key(),new_research_key()
    context={"market":"Tech100","uic":"4912","start":START.isoformat(),
             "end":(START+timedelta(minutes=5)).isoformat(),"mode":"1m",
             "costs":{"spread_bps":1.}}
    report={"pnl_nok":40.,"return_pct":.4,"drawdown_pct":.1,
            "total_cost_nok":4.,"trades":2,"gaps":0,"financing_nok":0.}
    ident=save_experiment(token=owner,label="V1",plan=PRESETS["Trend Long / Flat"],
          context=context,results=report,db_path=db)
    assert len(list_experiments(token=owner,db_path=db))==1
    assert len(list_experiments(token=other,db_path=db))==0
    assert load_experiment(token=other,experiment_id=ident,db_path=db) is None
    assert load_experiment(token=owner,experiment_id=ident,db_path=db)["results"]["pnl_nok"]==40
    with pytest.raises(ValueError):
        save_experiment(token=owner,label="bad",plan=PRESETS["Trend Long / Flat"],
                        context={**context,"saxo_oauth_token":"secret"},
                        results=report,db_path=db)


def test_standalone_sandbox_denied_with_any_production_secret():
    assert not standalone_worker_ready(env={},docker_binary="/usr/bin/docker")
    assert not standalone_worker_ready(
        env={"ALGORITHM_LAB_DEDICATED_SANDBOX":"yes",
             "DATABASE_URL":"postgres://secret"},docker_binary="/usr/bin/docker")
    assert standalone_worker_ready(
        env={"ALGORITHM_LAB_DEDICATED_SANDBOX":"yes"},
        docker_binary="/usr/bin/docker")
    docker=build_docker_command()
    assert "--network" in docker and "none" in docker
    assert "--cap-drop" in docker and "ALL" in docker
    assert "--read-only" in docker
    assert "--pids-limit" in docker and "--memory" in docker
    with pytest.raises(RuntimeError):
        execute_in_isolated_container(code=DEFAULT_CODE,bars=make_bars(3),env={},
                                      docker_binary="/usr/bin/docker")


def test_replayed_python_directions_use_next_bar_not_same_bar():
    bars=make_bars(16)
    dirs=tuple([1]*12+[0]*4)
    r=replay_directions(bars=bars,directions=dirs,costs=LabCosts(
        point_value_nok=1.,starting_nav_nok=10000.,spread_bps=0.,slippage_bps=0.),
        start_at=START,end_at=START+timedelta(minutes=16))
    assert r.trades[0].at == START+timedelta(minutes=1)
    assert all(t.after>=0 for t in r.trades)
    with pytest.raises(ValueError):
        replay_directions(bars=bars,directions=dirs[:-1],
            costs=LabCosts(),start_at=START,end_at=START+timedelta(minutes=16))
