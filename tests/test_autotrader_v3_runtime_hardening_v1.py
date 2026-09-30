"""Regression checks for live V3 durable request identity and account isolation."""
from pathlib import Path
import pytest
from autotrader_v3_live_saxo_v1 import SaxoLivePilotClientV3
from saxo_trading import SaxoTradingSafetyError
from saxo_provider import LIVE_BASE_URL


def test_all_runtime_status_updates_use_reserved_request_key():
    source=Path('autotrader_v3_live_runtime_v1.py').read_text()
    assert 'reserve_order_v3(request_key=request_key' in source
    assert source.count('mark_order_v3(request_key=request_key')==4
    assert 'mark_order_v3(request_key=decision.decision_key' not in source


def test_exact_positions_reject_missing_account_identity():
    class Client:
        base_url=LIVE_BASE_URL
        def _get(self,*args,**kwargs):
            return {'Data':[{'NetPositionBase':{'Uic':4912,'AssetType':'CfdOnIndex'}}]}
    broker=SaxoLivePilotClientV3(Client())
    with pytest.raises(SaxoTradingSafetyError,match='missing exact account'):
        broker.net_positions_exact(account_id='a',uic=4912,asset_type='CfdOnIndex')


def test_signed_inventory_exact_is_scoped_to_account_and_uses_gross_legs():
    class Client:
        base_url=LIVE_BASE_URL
        def _get(self,*args,**kwargs):
            return {'Data':[
                {'NetPositionBase':{'PositionsAccount':'other','Uic':4912,'AssetType':'CfdOnIndex','AmountLong':0.19,'AmountShort':0.03}},
                {'NetPositionBase':{'PositionsAccount':'v3','Uic':4912,'AssetType':'CfdOnIndex','AmountLong':0.00,'AmountShort':0.02}},
            ]}
    broker=SaxoLivePilotClientV3(Client())
    assert broker.signed_inventory_exact(account_id='v3',uic=4912,asset_type='CfdOnIndex') == pytest.approx(-0.02)
    assert broker.signed_inventory_exact(account_id='missing',uic=4912,asset_type='CfdOnIndex') == 0.0


def test_live_runtime_uses_v3_exact_inventory_reader_not_v2_portfolio_reader():
    source=Path('autotrader_v3_live_runtime_v1.py').read_text()
    assert 'broker.signed_inventory_exact(' in source
    assert '_position_observations_v2' not in source
