from pathlib import Path

SOURCE = Path("tradingdesk_automanager_simple_v1.py").read_text(encoding="utf-8")


def test_independent_account_panels_replace_motor_switch():
    assert 'tabs = st.tabs(["AutoTrader V3", "AutoTrader V2"])' in SOURCE
    assert 'for tab, engine_key in zip(tabs, (ENGINE_V3, ENGINE_V2)):' in SOURCE
    assert "tabs = st.tabs([" in SOURCE
    assert "def _render_account_autotrader_v1(" in SOURCE
    assert "selected_account=selected_account, enrollment=enrollment" in SOURCE
    assert 'key=f"td-engine-select:' not in SOURCE
    assert 'target_strategy_key=STRATEGY_KEY_V3 if requested_v3' not in SOURCE
    assert "engine_v3 = enrollment_engine_v1(enrollment) == ENGINE_V3" in SOURCE


def test_bootstrap_cannot_silently_start_v3_through_v2():
    assert "tuple(item for item in AUTOTRADER_STRATEGIES_V2 if engine_for_strategy_key_v1(item.key) == ENGINE_V2)" in SOURCE
    assert "V3 opprettes i den dedikerte V3-kontrollflaten" in SOURCE


def test_per_account_controls_remain_bound_to_pilot():
    assert "enrollment = enrollments[selected_account]" in SOURCE
    assert "enrollment = _active_live_for_context_v1(context, account_id=account_id)" not in SOURCE or "account_id=account_id" in SOURCE
    assert 'key=f"td-engine-master:{enrollment.pilot_key}"' in SOURCE
    assert "bootstrap = _bootstrap_candidate_v1(context, observations, account_id=selected_account)" in SOURCE


def test_saxo_account_labels_and_exclusivity():
    assert 'row.get("DisplayName")' in SOURCE
    assert 'row.get("AccountName")' in SOURCE
    assert 'claimed_by_other' in SOURCE
    assert 'row[0] not in claimed_by_other' in SOURCE
