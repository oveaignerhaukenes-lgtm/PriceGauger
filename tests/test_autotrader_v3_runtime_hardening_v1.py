"""Regression checks for live V3 durable request identity and account isolation."""
from pathlib import Path
import pytest
from autotrader_v3_live_saxo_v1 import SaxoLivePilotClientV3
from saxo_trading import SaxoTradingSafetyError
from saxo_provider import LIVE_BASE_URL


def test_all_runtime_status_updates_use_reserved_request_key():
    source=Path('autotrader_v3_live_runtime_v1.py').read_text()
    assert 'reserve_order_v3(request_key=request_key' in source
    assert source.count('mark_order_v3(request_key=request_key')==3
    assert 'mark_order_v3(request_key=decision.decision_key' not in source


def test_exact_positions_reject_missing_account_identity():
    class Client:
        base_url=LIVE_BASE_URL
        def _get(self,*args,**kwargs):
            return {'Data':[{'NetPositionBase':{'Uic':4912,'AssetType':'CfdOnIndex'}}]}
    broker=SaxoLivePilotClientV3(Client())
    with pytest.raises(SaxoTradingSafetyError,match='missing exact account'):
        broker.net_positions_exact(account_id='a',uic=4912,asset_type='CfdOnIndex')
