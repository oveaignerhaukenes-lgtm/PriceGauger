from pathlib import Path

PAGE=Path("pages/0_AutoTrader_V3.py").read_text(encoding="utf-8")


def test_stale_pending_release_disarms_before_unlocking():
    disarm='set_live_authority_v3(trader_id, False)'
    release='mark_order_v3('
    assert disarm in PAGE
    assert release in PAGE
    assert PAGE.index(disarm) < PAGE.index(release)
    assert 'state="REJECTED"' in PAGE


def test_stale_pending_release_is_explicit_operator_action():
    assert 'if st.button("Frigi gammel pending-lock og slå LIVE av"' in PAGE
    assert 'pending_order_v3(' in PAGE
