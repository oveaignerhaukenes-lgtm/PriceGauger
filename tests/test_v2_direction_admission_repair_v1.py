from pathlib import Path


def test_v2_missing_direction_admission_can_only_inherit_same_product_safety():
    source=Path("autotrader_entry_policy_v2.py").read_text()
    assert "_repair_direction_admission_from_same_product_v2" in source
    assert "sibling.market_id != enrollment.market_id" in source
    assert "sibling.instrument_id != enrollment.instrument_id" in source
    assert "sibling.market_name != enrollment.market_name" in source
    assert "negative_balance_protection_verified=sibling.negative_balance_protection_verified" in source


def test_v2_without_saved_admission_still_requires_margin_envelope():
    source=Path("autotrader_entry_policy_v2.py").read_text()
    start=source.index("def require_entry_policy_v2")
    body=source[start:start+2600]
    assert 'raise ValueError("NOT_IN_PG_PRODUCT_UNIVERSE")' not in body
    assert 'raise ValueError("MARGIN_ENVELOPE_NOT_ACTIVE")' in body
