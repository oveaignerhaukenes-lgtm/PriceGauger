from pathlib import Path


def test_live_on_provisions_missing_margin_envelope_before_authority():
    source = Path("autotrader_manage_control_v1.py").read_text()
    start = source.index("def set_auto_manage_enabled_v1")
    body = source[start:source.index("def set_position_management_enabled_v1")]
    assert "_ensure_live_margin_envelope_v1(enrollment)" in body
    assert body.index("_ensure_live_margin_envelope_v1(enrollment)") < body.index("INSERT INTO pg_v2_autotrader_product_manage_control")


def test_missing_envelope_uses_single_v2_live_default():
    source = Path("autotrader_manage_control_v1.py").read_text()
    helper = source[source.index("def _ensure_live_margin_envelope_v1"):source.index("def guard_block_state_v1")]
    assert "if config is None:" in helper
    assert "DEFAULT_LIVE_MAX_EFFECTIVE_LEVERAGE_V2 = 5.0" in source
    assert "save_pilot_margin_config_v2(" in helper
    assert "enabled=True" in helper


def test_explicitly_disabled_envelope_remains_fail_closed():
    source = Path("autotrader_manage_control_v1.py").read_text()
    helper = source[source.index("def _ensure_live_margin_envelope_v1"):source.index("def guard_block_state_v1")]
    assert "if not config.enabled:" in helper
    assert 'raise ValueError("MARGIN_ENVELOPE_DISABLED")' in helper


def test_live_off_does_not_create_or_enable_envelope():
    source = Path("autotrader_manage_control_v1.py").read_text()
    start = source.index("def set_auto_manage_enabled_v1")
    body = source[start:source.index("def set_position_management_enabled_v1")]
    assert "if value:\n        _ensure_live_margin_envelope_v1(enrollment)" in body
