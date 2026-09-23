from pathlib import Path

def test_v3_hides_v2_strategy_family_controls():
    text=Path("tradingdesk_automanager_simple_v1.py").read_text(encoding="utf-8")
    v3=text.index('if engine_v3:\n        with st.container(border=True):')
    ret=text.index('return observations',v3)
    v2=text.index('strategy_col, settings_col',ret)
    assert v3 < ret < v2
    assert '"MACD-Trailing"' in text[v3:ret]
    assert "V2-strategifamilier gjelder ikke" in text[v3:ret]
