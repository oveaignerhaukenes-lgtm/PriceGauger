from pathlib import Path

def test_tradingdesk_engine_is_persisted_per_account_without_shared_switch():
    text=Path("tradingdesk_automanager_simple_v1.py").read_text(encoding="utf-8")
    assert 'for tab, engine_key in zip(tabs, ("V2", "V3")):' in text
    assert "engine_v3 = enrollment.strategy_key == STRATEGY_KEY_V3" in text
    assert "td-engine-select:" not in text
    assert "target_strategy_key=STRATEGY_KEY_V3 if requested_v3" not in text
    assert 'key=f"td-engine-master:{enrollment.pilot_key}"' in text
