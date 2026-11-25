from datetime import datetime,timedelta,timezone
import json
import pytest
from database import connect
from live_mirror_telemetry_v1 import _persist
from live_mirror_audit_v1 import persist_verified_fills,calibration_samples,collect_one_audit

NOW=datetime(2026,11,25,10,tzinfo=timezone.utc)


def test_exact_fill_evidence_cannot_use_wrong_account_or_reconciliation_clock(tmp_path):
    path=str(tmp_path/"m.db")
    with connect(path) as db:
        db.execute("""CREATE TABLE autotrader_v3_execution_events(request_key TEXT,instance_id TEXT,
            account_id TEXT,uic INTEGER,asset_type TEXT,broker_order_id TEXT,side TEXT,
            amount REAL,executed_at TEXT)""")
        db.execute("""CREATE TABLE lsim_hyper_quotes_1s(provider_uic INTEGER,asset_type TEXT,
            bid REAL,ask REAL,quote_at TEXT,received_at TEXT)""")
        db.execute("INSERT INTO autotrader_v3_execution_events VALUES('r','a','acc',4912,'CfdOnIndex','o','Buy',.01,?)",
                   ((NOW+timedelta(seconds=20)).isoformat(),))
        db.execute("INSERT INTO lsim_hyper_quotes_1s VALUES(4912,'CfdOnIndex',100,102,?,?)",
                   ((NOW+timedelta(seconds=3)).isoformat(),(NOW+timedelta(seconds=3)).isoformat()))
    decision="a|"+NOW.isoformat()
    batch=[("decision:"+decision,"a",decision,"DECISION",NOW.isoformat(),"{}"),
           ("submission:r","a",decision,"SUBMIT",(NOW+timedelta(seconds=2)).isoformat(),"{}")]
    _persist(batch,path)
    _persist(batch,path)
    fill={"o":{"price_source":"SAXO_FINAL_FILL","execution_price":102.2,
               "filled_at":NOW+timedelta(seconds=4)}}
    assert persist_verified_fills(fill,account_id="wrong",uic=4912,asset_type="CfdOnIndex",
                                  db_path=path,now=NOW+timedelta(seconds=30))==1
    assert calibration_samples(instance_id="a",db_path=path)[0]==()
    assert persist_verified_fills(fill,account_id="acc",uic=4912,asset_type="CfdOnIndex",
                                  db_path=path,now=NOW+timedelta(seconds=30))==1
    rows,missing=calibration_samples(instance_id="a",db_path=path)
    assert len(rows)==1 and missing==0
    assert rows[0].latency==4 and rows[0].signed_slippage==pytest.approx(.2)
    assert collect_one_audit(db_path=path,now=NOW+timedelta(seconds=30),
                            fetch=lambda *args,**kwargs: pytest.fail("unexpected audit"))=="NO_MISSING_FILLS"
    with connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM pg_live_mirror_trace_v1").fetchone()[0]==2


def test_optional_audit_is_durably_throttled_even_on_no_match(tmp_path):
    path=str(tmp_path/"m.db")
    with connect(path) as db:
        db.execute("""CREATE TABLE autotrader_v3_execution_events(request_key TEXT,instance_id TEXT,
            account_id TEXT,uic INTEGER,asset_type TEXT,broker_order_id TEXT,side TEXT,
            amount REAL,executed_at TEXT)""")
        db.execute("INSERT INTO autotrader_v3_execution_events VALUES('r','a','acc',4912,'CfdOnIndex','o','Sell',.01,?)",
                   (NOW.isoformat(),))
    _persist([("submission:r","a","a|bar","SUBMIT",NOW.isoformat(),"{}")],path)
    calls=[]
    def fetch(events,**kwargs):
        calls.append(kwargs)
        return {}
    assert collect_one_audit(db_path=path,now=NOW+timedelta(seconds=1),fetch=fetch)=="VERIFIED:0"
    assert collect_one_audit(db_path=path,now=NOW+timedelta(seconds=2),fetch=fetch)=="THROTTLED"
    assert len(calls)==1 and calls[0]["account_id"]=="acc"
