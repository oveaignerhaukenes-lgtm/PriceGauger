from pathlib import Path


def test_v2_user_authority_and_guard_interlock_are_separate():
    control=Path("autotrader_manage_control_v1.py").read_text()
    assert "guard_blocked BOOLEAN NOT NULL DEFAULT FALSE" in control
    assert "def set_guard_block_v1" in control
    assert "def clear_guard_block_v1" in control
    assert "return bool(value) and not bool(blocked)" in control
    # User ON must not itself erase a safety block.
    setter=control[control.index("def set_auto_manage_enabled_v1"):control.index("def set_position_management_enabled_v1")]
    assert "guard_blocked=FALSE" not in setter


def test_execution_guard_no_longer_rewrites_user_autotrade_off():
    source=Path("autotrader_execution_guard_v1.py").read_text()
    pause=source[source.index("def _pause"):source.index("def _enrollment")]
    assert "set_guard_block_v1" in pause
    assert "set_auto_manage_enabled_v1" not in pause
    assert 'clear_guard_block_v1(enrollment, expected_reason="UNEXPECTED_POSITION_ORIGIN")' in source


def test_v2_ui_surfaces_guard_block_separately():
    source=Path("tradingdesk_automanager_simple_v1.py").read_text()
    assert "guard_block_state_v1(enrollment)" in source
    assert "V2 runtime-blokkert av execution guard" in source
