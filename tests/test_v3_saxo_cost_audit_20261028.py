"""Read-only Saxo source accounting and per-instrument BBO cost evidence."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import pytest

from autotrader_saxo_cost_evidence_v1 import (
    parse_saxo_transactions_costs,fetch_saxo_historical_costs,
    archived_bbo_spread,simple_roundtrip_quote_friction,
)
from database import connect


def test_transaction_costs_are_exact_account_and_uic_no_double_count():
    rows=[
        dict(AccountId="A",Instrument={"Uic":4912},Currency="NOK",
             Date="2026-10-28T10:00:00Z",TotalCost=-.8,RealizedPnL=2.5,
             Trades=[{"SpreadCost":.3}],Bookings=[{"BookedAmount":-.8}]),
        dict(AccountId="A",Instrument={"Uic":4912},Currency="NOK",
             Date="2026-10-28T10:05:00Z",TotalCost=-.6,RealizedPnL=-1.2),
        dict(AccountId="B",Instrument={"Uic":4912},Currency="NOK",
             Date="2026-10-28T10:00:00Z",TotalCost=-100.),
        dict(AccountId="A",Instrument={"Uic":99},Currency="NOK",
             Date="2026-10-28T10:00:00Z",TotalCost=-100.),
    ]
    result=parse_saxo_transactions_costs(
        transactions=rows,account_id="A",uic=4912)
    assert result.rows==2
    assert result.booked_cost_rows==2
    assert result.total_debits_abs==pytest.approx(1.4)
    assert result.signed_saxo_total_cost==pytest.approx(-1.4)
    assert result.realized_pnl_sum==pytest.approx(1.3)
    assert result.currency=="NOK"


def test_missing_and_mixed_cost_currency_are_unknown_not_zero():
    rows=[
        dict(AccountId="A",Instrument={"Uic":4912},Currency="NOK",
             Date="2026-10-28",TotalCost=None),
        dict(AccountId="A",Instrument={"Uic":4912},Currency="USD",
             Date="2026-10-28",TotalCost=-.8),
    ]
    r=parse_saxo_transactions_costs(
        transactions=rows,account_id="A",uic=4912)
    assert r.booked_cost_rows==1
    assert r.cost_unknown_rows==1
    assert r.signed_saxo_total_cost is None
    assert r.currency is None


def test_transactions_are_fetched_with_account_key_and_uic_get_only():
    class FakeClient:
        def __init__(self):self.calls=[]
        def _get(self,path,params=None):
            self.calls.append((path,params))
            return {"Data":[
                dict(AccountId="A",Instrument={"Uic":4912},
                     Currency="NOK",TotalCost=-1.5,
                     Date="2026-10-28T10:00:00Z")]
            }
    client=FakeClient()
    now=datetime(2026,10,28,10,0,tzinfo=timezone.utc)
    r=fetch_saxo_historical_costs(
        client=client,account_key="only-this-key",account_id="A",
        uic=4912,asset_type="CfdOnIndex",
        start=now-timedelta(days=3),end=now)
    assert r.rows==1
    assert client.calls[0][0]=="hist/v1/transactions"
    assert client.calls[0][1]["AccountKeys"]=="only-this-key"
    assert client.calls[0][1]["Uics"]=="4912"
    assert "$top" in client.calls[0][1]


def test_bbo_averages_separate_from_saxo_fees_and_reject_invalid(tmp_path):
    db=str(tmp_path/"cost.db")
    now=datetime(2026,10,28,10,0,tzinfo=timezone.utc)
    with connect(db) as connection:
        connection.execute("""CREATE TABLE lsim_hyper_quotes_1s(
            provider_uic INTEGER,quote_at TEXT,bid DOUBLE PRECISION,
            ask DOUBLE PRECISION)""")
        for i,spread in enumerate((1.,2.,3.,4.)):
            connection.execute(
                "INSERT INTO lsim_hyper_quotes_1s VALUES(?,?,?,?)",
                (4912,(now-timedelta(seconds=4-i)).isoformat(),
                 20000.,20000.+spread))
        connection.execute(
            "INSERT INTO lsim_hyper_quotes_1s VALUES(?,?,?,?)",
            (99,(now-timedelta(seconds=3)).isoformat(),
             100.,200.))
    result=archived_bbo_spread(
        uic=4912,hours=1,now=now,db_path=db,limit=1000)
    assert result.observations==4
    assert result.average_points==pytest.approx(2.5)
    assert result.p90_points==pytest.approx(3.)
    assert result.mean_bps is not None
    assert result.data_density_fraction==pytest.approx(4/3600.)
    assert simple_roundtrip_quote_friction(
        spread_points=2.5,point_value_nok_per_lot=10.,lots=.01)==.25


def test_page_is_analytical_only_no_precheck_or_trade():
    s=Path("pages/0_Saxo_Cost_Lab.py").read_text()
    nav=Path("navigation_config.py").read_text()
    source=Path("autotrader_saxo_cost_evidence_v1.py").read_text()
    assert "Saxo_Cost_Lab" in nav
    assert 'hist/v1/transactions' in source
    assert 'tradingconditions/cost' in source or '_verified_cost_probe' in source
    assert 'st.download_button(' in s
    for unsafe in ("place_order(", "set_live_authority_v3(",
                   "save_autotrader_config_v3(", "trade/v2/orders/precheck"):
        assert unsafe not in source
        assert unsafe not in s
