from pathlib import Path
from types import SimpleNamespace
from autotrader_v3_live_authority_v1 import set_live_authority_v3
from autotrader_v3_live_readiness_v1 import live_readiness_v3
from autotrader_v3_macd_trailing_v1 import STRATEGY_KEY_V3

def test_live_arm_is_user_authority_not_flat_only(tmp_path):
    db=str(tmp_path/"pg.db"); e=SimpleNamespace(strategy_key=STRATEGY_KEY_V3,execution_mode="LIVE_MANAGE",enabled=True,pilot_key="t")
    set_live_authority_v3("t",True,db_path=db)
    assert live_readiness_v3(e,broker_is_live=True,exact_inventory=.37,db_path=db).ready


def test_runtime_logs_enrollment_scan_without_account_secrets():
    source=Path("autotrader_v3_live_runtime_v1.py").read_text()
    assert "enrollment scan loaded=%d live=%d armed=%d candidates=%s" in source
    assert "AccountKey" not in source[source.index("enrollment scan loaded=%d live=%d armed=%d candidates=%s"):source.index("enrollment scan loaded=%d live=%d armed=%d candidates=%s")+500]
