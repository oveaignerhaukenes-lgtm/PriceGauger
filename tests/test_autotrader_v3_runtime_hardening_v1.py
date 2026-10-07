"""Regression checks for live V3 durable request identity and account isolation."""
from pathlib import Path
import pytest
from autotrader_v3_live_saxo_v1 import SaxoLivePilotClientV3
from saxo_trading import SaxoTradingSafetyError
from saxo_provider import LIVE_BASE_URL


def test_all_runtime_status_updates_use_reserved_request_key():
    source=Path('autotrader_v3_live_runtime_v1.py').read_text()
    assert 'reserve_order_v3(request_key=request_key' in source
    marked=source.count('mark_order_v3(')
    assert marked >= 5
    assert source.count('mark_order_v3(request_key=request_key') == marked
    assert 'mark_order_v3(request_key=decision.decision_key' not in source


def test_exact_positions_are_scoped_server_side_by_account_key():
    calls=[]
    class Client:
        base_url=LIVE_BASE_URL
        def _get(self,path,params=None):
            calls.append((path,params))
            if path=='port/v1/accounts/me':
                return {'Data':[{'AccountId':'v3','AccountKey':'ak','ClientKey':'ck'}]}
            assert path=='port/v1/netpositions'
            return {'Data':[{'NetPositionBase':{
                'AccountId':'v3','Uic':4912,'AssetType':'CfdOnIndex',
                'AmountLong':0.0,'AmountShort':0.03}}]}
    broker=SaxoLivePilotClientV3(Client())
    assert broker.signed_inventory_exact(account_id='v3',uic=4912,asset_type='CfdOnIndex') == pytest.approx(-0.03)
    path,params=calls[-1]
    assert path=='port/v1/netpositions'
    assert params['AccountKey']=='ak'
    assert params['ClientKey']=='ck'
    assert params['AssetType']=='CfdOnIndex'
    assert params['Uic']==4912


def test_exact_positions_reject_account_identity_mismatch():
    class Client:
        base_url=LIVE_BASE_URL
        def _get(self,path,params=None):
            if path=='port/v1/accounts/me':
                return {'Data':[{'AccountId':'v3','AccountKey':'ak','ClientKey':'ck'}]}
            return {'Data':[{'NetPositionBase':{
                'AccountId':'other','Uic':4912,'AssetType':'CfdOnIndex','Amount':0.03,
                'OpeningDirection':'Sell'}}]}
    broker=SaxoLivePilotClientV3(Client())
    with pytest.raises(SaxoTradingSafetyError,match='identity mismatch'):
        broker.net_positions_exact(account_id='v3',uic=4912,asset_type='CfdOnIndex')


def test_account_scoped_response_may_omit_redundant_account_id():
    class Client:
        base_url=LIVE_BASE_URL
        def _get(self,path,params=None):
            if path=='port/v1/accounts/me':
                return {'Data':[{'AccountId':'v3','AccountKey':'ak','ClientKey':'ck'}]}
            return {'Data':[{'NetPositionBase':{
                'Uic':4912,'AssetType':'CfdOnIndex','Amount':0.02,'OpeningDirection':'Sell'}}]}
    broker=SaxoLivePilotClientV3(Client())
    assert broker.signed_inventory_exact(account_id='v3',uic=4912,asset_type='CfdOnIndex') == pytest.approx(-0.02)


def test_live_runtime_uses_v3_exact_inventory_reader_not_v2_portfolio_reader():
    source=Path('autotrader_v3_live_runtime_v1.py').read_text()
    assert 'broker.signed_inventory_exact(' in source
    assert '_position_observations_v2' not in source


def test_open_pnl_uses_rich_view_but_preserves_exact_account_product_match():
    class Client:
        base_url=LIVE_BASE_URL
        def _get(self,path,params=None):
            if path=='port/v1/accounts/me':
                return {'Data':[{'AccountId':'v3','AccountKey':'ak','ClientKey':'ck'}]}
            if path=='port/v1/netpositions':
                return {'Data':[{'NetPositionBase':{'Uic':4912,'AssetType':'CfdOnIndex','AmountLong':0.01}}]}
            if path=='port/v1/netpositions/me':
                return {'Data':[{'NetPositionBase':{'PositionsAccount':'v3','Uic':4912,'AssetType':'CfdOnIndex','AmountLong':0.01},'NetPositionView':{'AverageOpenPriceIncludingCosts':100.0,'CurrentPrice':99.0}}]}
            raise AssertionError(path)
    broker=SaxoLivePilotClientV3(Client())
    assert broker.open_pnl_exact(account_id='v3',uic=4912,asset_type='CfdOnIndex') < 0
