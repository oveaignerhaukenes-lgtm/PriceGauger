from pathlib import Path


def test_persisted_product_safety_hides_redundant_nbp_acknowledgement():
    source = Path("tradingdesk_autotrade_entry_gate_v2.py").read_text(encoding="utf-8")
    admissions_index = source.index("admissions = {")
    verified_index = source.index("all_safety_verified =")
    verified_branch_index = source.index("if all_safety_verified:")
    nbp_checkbox_index = source.index('"Jeg har verifisert at denne Saxo-kontoen har negative balance protection')

    assert admissions_index < verified_index < verified_branch_index < nbp_checkbox_index
    assert "Kontobeskyttelsen for dette eksakte Saxo-produktet er allerede verifisert og lagret" in source


def test_live_open_acknowledgement_only_renders_when_arming_is_needed():
    source = Path("tradingdesk_autotrade_entry_gate_v2.py").read_text(encoding="utf-8")
    arming_branch = source.index("if not enrollment.live_open_armed:")
    entry_ack = source.index("entry_ack = st.checkbox(")
    arm_button = source.index('"Arm LIVE re-entry"')
    disarm_button = source.index('"Disarm LIVE re-entry"')

    assert arming_branch < entry_ack < arm_button < disarm_button


def test_close_acknowledgement_stays_adjacent_to_its_own_authority_action():
    source = Path("tradingdesk_autotrade_entry_gate_v2.py").read_text(encoding="utf-8")
    ack = source.index("close_ack = st.checkbox(")
    arm = source.index('"Arm automatisk LIVE CLOSE"')
    save = source.index("save_live_close_config_v1", ack)

    assert ack < arm < save
