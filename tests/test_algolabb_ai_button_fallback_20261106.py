"""AI draft action must not be blocked by an invalid/blank JSON editor."""
from pathlib import Path


def test_ai_draft_has_preset_fallback_and_preserves_paper_validation():
    source = (Path(__file__).resolve().parent.parent / "pages/0_Algorithm_Lab.py").read_text()
    assert "ai_base_plan = plan if plan is not None else validate_plan(PRESETS[preset])" in source
    assert "disabled=not user_request.strip(), key=\"alg:generate\"" in source
    assert "request=user_request, current_plan=ai_base_plan," in source
    assert "plan = validate_plan(json.loads(plan_text))" in source
    assert "plan = None" in source
    assert "st.session_state[\"alg:pending_plan\"] = suggestion[\"plan\"]" in source
    assert "st.rerun()" in source
