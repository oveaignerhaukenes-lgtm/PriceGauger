"""Read-only pending-account attribution may not change any execution decision."""
from pathlib import Path


def test_pending_audit_uses_existing_account_listing_and_same_fail_closed_wait():
    src=(Path(__file__).resolve().parent.parent / "autotrader_v3_live_runtime_v1.py").read_text()
    assert src.count("for row in broker.accounts():") == 1
    assert "row.get('AccountName') or row.get('DisplayName')" in src
    assert "_PENDING_AUDIT_LOGGED_V3=set()" in src
    wait=src.index("elif reconciliation.state=='WAIT':")
    following=src.index("else:", wait)
    section=src[wait:following]
    assert "if e.pilot_key not in _PENDING_AUDIT_LOGGED_V3:" in section
    assert "action=READ_ONLY_NO_RETRY" in section
    assert "LOGGER.warning(" in section
    assert "account_labels.get(e.account_id)" in section
    assert "pending.get('broker_order_id')" in section
    assert "mark_order_v3(" not in section
    assert "broker.place_order(" not in section
    assert "broker.precheck(" not in section
    assert "_record_runtime(e.pilot_key,'PENDING'" in section


def test_saxo_pending_intent_never_automatically_expires():
    src=(Path(__file__).resolve().parent.parent / "autotrader_v3_live_runtime_v1.py").read_text()
    wait=src.index("elif reconciliation.state=='WAIT':")
    section=src[wait:src.index("else:", wait)]
    assert "no retry sent" in section
    assert "READ_ONLY_NO_RETRY" in section
    assert "updated_at" in section
