from pathlib import Path


def test_v3_hides_v2_strategy_family_controls():
    text=Path("tradingdesk_automanager_simple_v1.py").read_text(encoding="utf-8")
    marker=text.index("# TradingDesk is deliberately only the cockpit summary for V3.")
    ret=text.index("return observations",marker)
    v2=text.index("strategy_col, settings_col",ret)
    assert marker < ret < v2
    block=text[marker:ret]
    assert "AutoTrader V3" in block
    assert "Strategi, periode, modifiers, SIM-Adapt, Overseer og God Mode" in block
    assert "render_strategy_family_builder_v1" not in block
