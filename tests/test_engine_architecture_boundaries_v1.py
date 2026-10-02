from pathlib import Path

from autotrader_engine_identity_v1 import ENGINE_V2, ENGINE_V3, engine_for_strategy_key_v1

ROOT = Path(__file__).resolve().parents[1]
SHARED_UI = ROOT / "tradingdesk_automanager_simple_v1.py"

def test_engine_identity_classifies_v3_without_runtime_imports():
    assert engine_for_strategy_key_v1("macd-trailing-v1") == ENGINE_V3
    assert engine_for_strategy_key_v1("macd-histogram-v1") == ENGINE_V3
    assert engine_for_strategy_key_v1("macd-stoch-v1") == ENGINE_V3
    assert engine_for_strategy_key_v1("macd-flip-v2") == ENGINE_V2

def test_engine_identity_module_has_no_authority_imports():
    source = (ROOT / "autotrader_engine_identity_v1.py").read_text()
    assert "live_authority" not in source
    assert "sim_authority" not in source
    assert "manage_control" not in source

def test_shared_ui_uses_control_plane_not_v3_authority_storage():
    source = SHARED_UI.read_text()
    assert "autotrader_v3_live_authority_v1" not in source
    assert "autotrader_v3_sim_authority_v1" not in source
    assert "autotrader_v3_control_plane_v1" in source
