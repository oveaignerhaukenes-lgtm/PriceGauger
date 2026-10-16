"""Regression checks for live V3 durable request identity and account isolation."""
from pathlib import Path
import ast
import pytest
from autotrader_v3_live_saxo_v1 import SaxoLivePilotClientV3
from saxo_trading import SaxoTradingSafetyError
from saxo_provider import LIVE_BASE_URL


def test_all_runtime_status_updates_use_reserved_request_key():
    source=Path('autotrader_v3_live_runtime_v1.py').read_text()
    assert 'reserve_order_v3(request_key=request_key' in source
    tree=ast.parse(source)
    calls=[
        node for node in ast.walk(tree)
        if isinstance(node,ast.Call)
        and isinstance(node.func,ast.Name)
        and node.func.id=='mark_order_v3'
    ]
    assert len(calls) >= 5
    for call in calls:
        request_kw=next((kw for kw in call.keywords if kw.arg=='request_key'),None)
        assert request_kw is not None
        identity=ast.unparse(request_kw.value)
        assert identity in {"request_key", "pending['request_key']"}


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


def test_open_pnl_uses_single_account_scoped_response_and_no_client_wide_me():
    calls=[]
    class Client:
        base_url=LIVE_BASE_URL
        def _get(self,path,params=None):
            calls.append((path,params))
            if path=='port/v1/accounts/me':
                return {'Data':[{'AccountId':'v3','AccountKey':'ak','ClientKey':'ck'}]}
            if path=='port/v1/netpositions':
                assert params['AccountKey']=='ak'
                assert params['Uic']==4912
                assert params['FieldGroups']=='NetPositionBase,NetPositionView'
                return {'Data':[{
                    'NetPositionBase':{
                        'PositionsAccount':'v3','Uic':4912,
                        'AssetType':'CfdOnIndex','AmountLong':0.01
                    },
                    'NetPositionView':{
                        'ProfitLossOnTradeInBaseCurrency':-12.5,
                        'CalculationReliability':'Ok','CurrentPriceDelayMinutes':0,
                        'AverageOpenPriceIncludingCosts':100.0,
                        'CurrentPrice':101.0
                    }
                }]}
            raise AssertionError("Unexpected, unscoped Saxo path: "+path)
    broker=SaxoLivePilotClientV3(Client())
    assert broker.open_pnl_exact(account_id='v3',uic=4912,
                                  asset_type='CfdOnIndex') == pytest.approx(-12.5)
    assert [path for path,params in calls].count('port/v1/netpositions')==1
    assert 'port/v1/netpositions/me' not in [path for path,params in calls]


def test_account_scoped_pnl_rejects_other_account_and_incomplete_pagination():
    for shape in ('wrong_account','pagination','missing_view'):
        class Client:
            base_url=LIVE_BASE_URL
            def _get(self,path,params=None):
                if path=='port/v1/accounts/me':
                    return {'Data':[{'AccountId':'v3','AccountKey':'ak'}]}
                if path!='port/v1/netpositions':
                    raise AssertionError(path)
                row={
                    'NetPositionBase':{
                        'PositionsAccount':'other' if shape=='wrong_account' else 'v3',
                        'Uic':4912,'AssetType':'CfdOnIndex','AmountLong':.01},
                    'NetPositionView':{'ProfitLossOnTradeInBaseCurrency':-10.,
                        'CalculationReliability':'Ok','CurrentPriceDelayMinutes':0},
                }
                if shape=='missing_view':
                    row.pop('NetPositionView')
                result={'Data':[row]}
                if shape=='pagination':result['__next']='?skip=1000'
                return result
        broker=SaxoLivePilotClientV3(Client())
        with pytest.raises(SaxoTradingSafetyError):
            broker.open_pnl_exact(account_id='v3',uic=4912,
                                   asset_type='CfdOnIndex')
