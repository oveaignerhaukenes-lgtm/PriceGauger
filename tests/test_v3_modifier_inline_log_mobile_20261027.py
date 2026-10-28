"""Regression: narrow-phone modifier rows show complete labels and lazy logs.

All ordinary page reruns must NOT execute per-modifier history/fill scans.
"""
from pathlib import Path


def test_mobile_modifier_is_readable_three_part_one_row():
    ui=Path("autotrader_v3_instance_controls_ui_v1.py").read_text()
    dependencies=Path("requirements.txt").read_text()
    head=ui.index("    for item in other_modifiers:")
    tail=ui.index("    mode=st.selectbox(",head)
    block=ui[head:tail]
    assert 'toggle_col,label_col,log_col=st.columns(' in block
    assert '[1.12,4.8,0.88],gap="small",vertical_alignment="center",wrap=False' in block
    assert 'chosen_modifier=toggle_col.toggle(' in block
    assert 'label_visibility="collapsed"' in block
    assert "label_col.markdown(" in block
    assert '"white-space:normal;overflow-wrap:anywhere;' in block
    assert 'log_col.button(' in block
    assert 'width=40' in block
    assert '_show_modifier_log_v3(' in block
    assert 'with right.popover(' not in block
    assert "streamlit>=1.62,<2" in dependencies


def test_log_queries_are_lazy_and_only_after_click():
    ui=Path("autotrader_v3_instance_controls_ui_v1.py").read_text()
    helper=ui[ui.index('@st.dialog("Modifikatorlogg"'):ui.index("def render_v3_instance_controls_v1(")]
    block=ui[ui.index("    for item in other_modifiers:"):ui.index("    mode=st.selectbox(")]
    assert "load_modifier_live_events_v3(" in helper
    assert "load_exact_reconciled_executions_v3(" in helper
    assert "load_modifier_live_events_v3(" not in block
    assert "load_exact_reconciled_executions_v3(" not in block
    assert 'if log_col.button(' in block
    assert "unsafe_allow_html=True" in block
    assert "escape(help_text,quote=True)" in block


def test_unimplemented_live_modifiers_cannot_be_newly_toggled_on():
    ui=Path("autotrader_v3_instance_controls_ui_v1.py").read_text()
    block=ui[ui.index("    for item in other_modifiers:"):ui.index("    mode=st.selectbox(")]
    assert "not is_live and item.key not in config.modifiers" in block
    assert "chosen_modifier or (is_ai_preset" in block
