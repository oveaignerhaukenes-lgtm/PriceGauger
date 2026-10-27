"""Regression: modifier audit affordance stays in-line on narrow phones.

No Streamlit widgets are invoked in this test; it verifies the structural
UI contract and minimum supported no-wrap layout API.
"""
from pathlib import Path


def test_mobile_modifier_log_is_one_row_icon_control():
    ui=Path("autotrader_v3_instance_controls_ui_v1.py").read_text()
    dependencies=Path("requirements.txt").read_text()
    head=ui.index("for item in other_modifiers:")
    tail=ui.index("    mode=st.selectbox(",head)
    block=ui[head:tail]
    assert 'left,right=st.columns(' in block
    assert '[3,1],gap="small",vertical_alignment="center",wrap=False' in block
    assert "chosen_modifier=left.toggle(" in block
    assert "wrap=False," in block
    assert 'with right.popover(' in block
    assert '"📖",width="content",wrap=False' in block
    assert block.index("left,right=st.columns(") < block.index("chosen_modifier=left.toggle(")
    assert block.index("chosen_modifier=left.toggle(") < block.index("with right.popover(")
    assert "load_modifier_live_events_v3(" in block
    assert "load_exact_reconciled_executions_v3(" in block
    assert "streamlit>=1.62,<2" in dependencies
