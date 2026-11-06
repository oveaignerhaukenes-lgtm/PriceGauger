"""Regression: blank persisted Streamlit plan must recover its selected preset."""
from pathlib import Path


def test_algolabb_restores_blank_plan_without_erasing_nonempty_code():
    src = (Path(__file__).resolve().parent.parent / "pages/0_Algorithm_Lab.py").read_text()
    assert 'blank_plan = not str(st.session_state.get("alg:editable_plan") or "").strip()' in src
    assert 'elif preset_changed or blank_plan:' in src
    assert 'st.session_state["alg:editable_plan"] = json.dumps(PRESETS[preset]' in src
    assert 'st.button("Gjenopprett valgt mal"' in src
    assert src.index('st.session_state["alg:last_preset"] = preset') < src.index('plan_text = st.text_area(')
    assert 'st.session_state.pop("alg:pending_plan", None)' in src
