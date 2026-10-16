from pathlib import Path

PAGE=Path("pages/0_AutoTrader_V3.py").read_text(encoding="utf-8")
CONTROLS=Path("autotrader_v3_instance_controls_ui_v1.py").read_text(encoding="utf-8")
RESET=Path("autotrader_v3_instance_reset_v1.py").read_text(encoding="utf-8")


def test_old_unverified_pending_release_removed():
    assert 'if st.button("Frigi gammel pending-lock og slå LIVE av"' not in PAGE
    assert 'mark_order_v3(' not in PAGE
    assert 'state="REJECTED"' not in PAGE
    assert 'render_v3_fleet_management_v1()' in PAGE


def test_instance_reset_uses_only_existing_verified_cas_recovery():
    assert "recover_stale_reserved_v3(" in RESET
    assert 'pending.get("state") != "RESERVED"' in RESET
    assert "Saxo LIVE er utilgjengelig" in RESET
    assert "reset_instance_safely_v3(instance_id=trader_id)" in CONTROLS
