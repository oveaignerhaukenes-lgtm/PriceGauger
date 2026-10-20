"""Saxo GET-only historical replay calibration and account return overlays."""
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from pathlib import Path
import pytest

from strategy_lab_v2_saxo_costs import (
    saxo_replay_costs_v2,verified_replay_costs_v2,saxobank_accounts_v2,
)
from strategy_lab_v2_accounts import _overlay_frame_v2
from strategy_lab_v2_replay import ReplayResultV2,ReplayPointV2


class Client:
    def __init__(self,*,details=True,cost=True):
        self.calls=[];self.details=details;self.cost=cost
    def _get(self,path,*,params=None):
        self.calls.append((path,params))
        if path=="port/v1/accounts/me":
            return {"Data":[{"AccountKey":"secret-fake",
                              "AccountId":"acct-lab","Currency":"NOK"}]}
        if path.startswith("ref/v1/instruments/details/"):
            if not self.details: raise ValueError("not available")
            return {"PriceCurrency":"USD","ContractSize":1.,
                    "MinimumTradeSize":.01,"IncrementSize":.01}
        if path.startswith("cs/v1/tradingconditions/cost/"):
            if not self.cost:raise ValueError("not available")
            return {"Cost":{
                "Long":{"Currency":"NOK","TradingCost":{
                    "Commissions":[{"Value":3.}]}},
                "Short":{"Currency":"NOK","TradingCost":{
                    "Commissions":[{"Value":3.}]}}
            }}
        raise ValueError(path)
    def info_price(self,inst):
        if inst.uic==500:return {"Quote":{"Bid":9.99,"Ask":10.01}}
        return {"Quote":{"Bid":1999.,"Ask":2001.}}
    def search_instruments(self,text,*,asset_types=""):
        if text=="USDNOK":
            from saxo_provider import SaxoInstrument
            return [SaxoInstrument(asset="fx",uic=500,asset_type="FxSpot",
                                   symbol="USDNOK")]
        return []


SOURCE=SimpleNamespace(market_name="Gold",provider_instrument_id="1001",
                       asset_type="CfdOnFutures",symbol="GOLD",
                       price_multiplier=1.)
ACCOUNT={"account_key":"secret-fake","account_id":"acct-lab","currency":"NOK"}


def test_verified_saxo_costs_exact_identity_and_no_order_writes():
    client=Client()
    assert saxobank_accounts_v2(client)[0]["account_id"]=="acct-lab"
    evidence=saxo_replay_costs_v2(client,source=SOURCE,account=ACCOUNT)
    assert evidence.status=="SAXO_COST_SCENARIO"
    assert evidence.product_uic==1001
    assert evidence.point_value_nok==pytest.approx(10.)
    assert evidence.spread_bps==pytest.approx(10.)
    assert evidence.fixed_commission_nok==3.
    costs=verified_replay_costs_v2(evidence)
    assert costs.lot_step==.01
    assert costs.source.startswith("SAXO_INDICATIVE_NOW")
    assert client.calls
    assert all(not path.startswith("trade/v2/orders") for path,_ in client.calls)
    assert all("secret-fake" not in str(x) for x in costs.__dict__.values())


def test_missing_saxo_evidence_fails_closed():
    for client in (Client(details=False),Client(cost=False)):
        ev=saxo_replay_costs_v2(client,source=SOURCE,account=ACCOUNT)
        assert ev.status=="INCOMPLETE"
        with pytest.raises(ValueError,match="verified"):
            verified_replay_costs_v2(ev)


def test_account_comparison_does_not_mix_nominal_nav_and_paper_units():
    at=datetime(2026,10,20,18,tzinfo=timezone.utc)
    sample=[{"observed_at":(at+timedelta(minutes=i*5)).isoformat(),
             "total_value":1000+10*i,"calculation_reliability":"Ok"}
            for i in range(4)]
    paper=ReplayResultV2(
        "macd-flip",tuple(ReplayPointV2(
            at+timedelta(minutes=i),100+i,10000+i,0.,.1,"HOLD"
        )for i in range(4)),(),0.,0,0.,.03,0,"SCENARIO")
    frame=_overlay_frame_v2(sample,{"macd-flip":paper})
    assert "Saxo kontoverdi % · uavstemt" in frame
    assert "PAPER · macd-flip" in frame
    assert frame.iloc[0,0]==0
    assert max(frame["Saxo kontoverdi % · uavstemt"])==pytest.approx(3.)
    assert max(frame["PAPER · macd-flip"])==pytest.approx(.03)


def test_navigation_old_strategy_lab_remains():
    nav=Path("navigation_config.py").read_text()
    assert "pages/0_Strategy_Lab_V2.py" in nav
    assert "pages/0_Strategy_Lab.py" in nav
    assert "pages/0_Live_Sim_Lab.py" in nav
