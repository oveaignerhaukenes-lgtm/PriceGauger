from pathlib import Path

def test_tradingdesk_engine_selector_is_first_class():
    text=Path("tradingdesk_automanager_simple_v1.py").read_text(encoding="utf-8")
    assert '"AutoTrader-motor"' in text
    assert '("V2", "V3")' in text
    assert "target_strategy_key=STRATEGY_KEY_V3 if requested_v3 else FAMILY_MACD_STRATEGY_V1" in text
    assert "set_live_authority_v3(switched.pilot_key, True)" in text
