from datetime import datetime, timedelta, timezone
import json
import pytest

from database import connect
from live_mirror_broker_v1 import MirrorTerms, MirrorAccount, MirrorQuote, execute_target
from live_mirror_registry_v1 import refresh_mirror_registry, mirror_snapshot

NOW=datetime(2026,11,25,10,0,tzinfo=timezone.utc)


def quote(sec,bid=100,ask=102,received=None):
    return MirrorQuote(NOW+timedelta(seconds=sec),
        NOW+timedelta(seconds=sec if received is None else received),bid,ask)


def terms(**kwargs):
    return MirrorTerms(**dict(dict(nok_per_point_per_lot=10,margin_fraction=.05,
        fee_nok_per_lot_per_side=1,latency_seconds=3,adverse_slippage_points=0,
        minimum_lots=.01,capital_cap_nok=300),**kwargs))


def test_bbo_execution_is_causal_and_spread_paid_once():
    a=MirrorAccount(300)
    result=execute_target(a,.01,decided_at=NOW,quotes=[quote(1),quote(4),quote(8)],
                          now=NOW+timedelta(seconds=4),terms=terms())
    assert result.status=="FILLED"
    assert result.price==102 and result.received_at==NOW+timedelta(seconds=4)
    assert result.account.equity(100,102,terms())==pytest.approx(299.79)
    close=execute_target(result.account,0,decided_at=NOW+timedelta(seconds=4),
                         quotes=[quote(8)],now=NOW+timedelta(seconds=8),terms=terms())
    assert close.price==100 and close.account.inventory==0
    assert close.account.cash_nok==pytest.approx(299.78)
    assert close.account.realized_nok==pytest.approx(-.2)
    assert close.account.fees_nok==pytest.approx(.02)


def test_no_future_or_stale_quotes_and_no_expired_fill():
    a=MirrorAccount(300)
    for q in (quote(7),quote(-1,received=4),quote(1,received=8)):
        result=execute_target(a,.01,decided_at=NOW,quotes=[q],
                              now=NOW+timedelta(seconds=4),terms=terms())
        assert result.status=="WAIT_QUOTE"
        assert result.account==a
    assert execute_target(a,.01,decided_at=NOW,quotes=[quote(11)],
            now=NOW+timedelta(seconds=12),terms=terms()).status=="QUOTE_EXPIRED"


def test_margin_and_flat_boundary_are_independent_per_account():
    richer=MirrorAccount(300)
    poorer=MirrorAccount(.01)
    args=dict(decided_at=NOW,quotes=[quote(4)],now=NOW+timedelta(seconds=4),terms=terms())
    assert execute_target(richer,.01,**args).status=="FILLED"
    assert execute_target(poorer,.01,**args).status=="MARGIN_REJECTED"
    short=execute_target(richer,-.01,**args).account
    reverse=execute_target(short,.01,**args)
    assert reverse.status=="FILLED" and reverse.account.inventory==0
    assert reverse.price==102
    # Risk reductions must work even on a negative-cash account.
    assert execute_target(MirrorAccount(-10,-.01,100),0,**args).status=="FILLED"


def test_discovery_is_read_only_on_source_tables_and_versions_settings(tmp_path):
    path=str(tmp_path/"mirror.db")
    with connect(path) as db:
        for sql in (
            "CREATE TABLE autotrader_v3_engine_instances(instance_id TEXT,account_id TEXT,uic INTEGER,asset_type TEXT,instrument_id INTEGER,market_name TEXT,enabled BOOLEAN)",
            "CREATE TABLE autotrader_v3_live_authority(trader_id TEXT,armed BOOLEAN)",
            "CREATE TABLE autotrader_v3_config(trader_id TEXT,strategy_key TEXT,timeframe TEXT,control_mode TEXT,modifiers_json TEXT,regime_timeframe TEXT,exit_timeframe TEXT)",
            "CREATE TABLE autotrader_v3_execution_policy(trader_id TEXT,budget_nok REAL,exposure_pct REAL)",
            "CREATE TABLE pg_v3_regime_entry_policy_v1(instance_id TEXT,strategy_key TEXT,mode TEXT,allow_bull INTEGER,allow_bear INTEGER,allow_sideways INTEGER,trend_only INTEGER,block_unknown INTEGER)",
            "CREATE TABLE pg_v3_trade_filter_control_v1(instance_id TEXT,strategy_key TEXT,mode TEXT,source TEXT)",
            "CREATE TABLE autotrader_v3_modifier_settings(trader_id TEXT,modifier_key TEXT,settings_json TEXT)",
            "CREATE TABLE autotrader_v3_live_runtime_state(trader_id TEXT,status TEXT,detail TEXT,updated_at TEXT)",
            "CREATE TABLE pg_saxo_account_truth_v1(account_id TEXT,account_name TEXT,currency TEXT,total_value REAL,cash_balance REAL,margin_used REAL,margin_utilization_pct REAL,calculation_reliability TEXT,observed_at TEXT)",
            "CREATE TABLE lsim_hyper_quotes_1s(provider_uic INTEGER,asset_type TEXT,quote_at TEXT,received_at TEXT,bid REAL,ask REAL)",
            "CREATE TABLE autotrader_v3_order_guard(account_id TEXT,uic INTEGER,asset_type TEXT,state TEXT)",
        ):
            db.execute(sql)
        for identity,armed in (("a",True),("b",False)):
            db.execute("INSERT INTO autotrader_v3_engine_instances VALUES(?,?,?,?,?,?,TRUE)",
                       (identity,identity+"account",4912,"CfdOnIndex",42,"Tech100"))
            db.execute("INSERT INTO autotrader_v3_live_authority VALUES(?,?)",(identity,armed))
        db.execute("INSERT INTO autotrader_v3_config VALUES('a','macd-stoch-v2-1','2m','Manuell','[]','5m','2m')")
        db.execute("INSERT INTO autotrader_v3_execution_policy VALUES('a',300,100)")
        db.execute("INSERT INTO pg_v3_regime_entry_policy_v1 VALUES('a','macd-stoch-v2-1','LIVE',1,0,0,0,1)")
        db.execute("INSERT INTO pg_v3_trade_filter_control_v1 VALUES('a','macd-stoch-v2-1','GO','OPERATOR')")
        db.execute("INSERT INTO autotrader_v3_live_runtime_state VALUES('a','MANAGING','actual=0 target=0',?)",(NOW.isoformat(),))
        db.execute("INSERT INTO pg_saxo_account_truth_v1 VALUES('aaccount','A','NOK',300,300,0,0,'Ok',?)",(NOW.isoformat(),))
        db.execute("INSERT INTO lsim_hyper_quotes_1s VALUES(4912,'CfdOnIndex',?,?,100,102)",(NOW.isoformat(),NOW.isoformat()))
    assert refresh_mirror_registry(db_path=path,now=NOW)==1
    first=mirror_snapshot(db_path=path)[0]
    assert first["status"]=="WAIT_CALIBRATION"
    assert json.loads(first["config_json"])["regime"]["mode"]=="LIVE"
    assert refresh_mirror_registry(db_path=path,now=NOW)==1
    assert mirror_snapshot(db_path=path)[0]["mirror_id"]==first["mirror_id"]
    with connect(path) as db:
        db.execute("UPDATE autotrader_v3_config SET timeframe='5m' WHERE trader_id='a'")
    refresh_mirror_registry(db_path=path,now=NOW)
    assert mirror_snapshot(db_path=path)[0]["mirror_id"]!=first["mirror_id"]
    with connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM pg_live_mirror_registry_v1").fetchone()[0]==2
        assert db.execute("SELECT COUNT(*) FROM autotrader_v3_live_authority WHERE armed=TRUE").fetchone()[0]==1
        db.execute("UPDATE autotrader_v3_live_runtime_state SET detail='actual=0.01 target=0.01' WHERE trader_id='a'")
    refresh_mirror_registry(db_path=path,now=NOW)
    assert mirror_snapshot(db_path=path)[0]["status"]=="WAIT_FLAT_BASELINE"
    with connect(path) as db:
        db.execute("UPDATE autotrader_v3_live_authority SET armed=FALSE")
    assert refresh_mirror_registry(db_path=path,now=NOW)==0
    assert mirror_snapshot(db_path=path)==()
