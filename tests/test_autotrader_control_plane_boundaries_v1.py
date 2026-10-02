from pathlib import Path


def test_v2_control_plane_owns_v2_account_claim_and_raw_authority():
    text = Path("autotrader_v2_control_plane_v1.py").read_text(encoding="utf-8")
    assert "claim_account_v1(account_id, ENGINE_V2" in text
    assert "set_position_management_enabled_v1" in text
    assert "set_auto_manage_enabled_v1" in text
    assert "autotrader_v3_" not in text


def test_v3_fleet_ui_uses_canonical_control_plane_only():
    text = Path("pages/6_AutoTrader_POC.py").read_text(encoding="utf-8")
    assert "from autotrader_v3_control_plane_v1 import" in text
    assert "set_live_enabled_v3" in text
    assert "set_sim_enabled_v3" in text
    assert "from autotrader_v3_live_authority_v1 import" not in text
    assert "from autotrader_v3_sim_authority_v1 import" not in text
    assert "set_live_authority_v3(" not in text
    assert "set_sim_authority_v3(" not in text


def test_shared_tradingdesk_does_not_mutate_raw_v3_authority():
    text = Path("tradingdesk_automanager_simple_v1.py").read_text(encoding="utf-8")
    assert "set_live_authority_v3(" not in text
    assert "set_sim_authority_v3(" not in text
