from pathlib import Path

def test_tradingdesk_has_explicit_engine_master_authority():
    text=Path("tradingdesk_automanager_simple_v1.py").read_text(encoding="utf-8")
    assert "ENGINE V2 · LIVE" in text
    assert "ENGINE V3 · LIVE" in text
    assert "Master authority" in text
    assert "set_live_authority_v3" in text
