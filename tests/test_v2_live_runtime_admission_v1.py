from pathlib import Path


def test_v2_live_policy_no_longer_requires_legacy_product_admission_row():
    source=Path("autotrader_entry_policy_v2.py").read_text()
    start=source.index("def require_entry_policy_v2")
    body=source[start:start+3300]
    assert 'raise ValueError("NOT_IN_PG_PRODUCT_UNIVERSE")' not in body
    assert "if admission is not None:" in body
    assert "MARGIN_ENVELOPE_NOT_ACTIVE" in body
    assert "require_breakeven_reentry_allowed_v1" in body


def test_v2_live_open_still_has_broker_prechecks_after_policy():
    source=Path("autotrader_live_open_legacy_v2.py").read_text()
    policy=source.index("require_entry_policy_v2(")
    tail=source[policy:policy+7000]
    assert "find_largest_legal_entry_v2(" in tail
    assert "precheck_entry_amount_v2(" in tail
    assert "FINAL_PRECHECK_OR_MARGIN_ENVELOPE_BLOCKED" in tail
