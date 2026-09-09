from __future__ import annotations

from pathlib import Path


def test_automanager_facade_mounts_pilot_status_below_controls() -> None:
    source = Path("tradingdesk_automanage_panel_v2.py").read_text(encoding="utf-8")
    assert "render_tradingdesk_automanager_simple_v1(context)" in source
    assert "render_tradingdesk_pilot_status_panel_v1(context)" in source


def test_pilot_status_panel_has_no_execution_mutations() -> None:
    source = Path("tradingdesk_pilot_status_panel_v1.py").read_text(encoding="utf-8")
    forbidden = (
        "request_manual_target_v2",
        "set_auto_manage_enabled_v1",
        "set_position_management_enabled_v1",
        "save_entry_sizing_policy_v2",
        "trade/v2/orders",
        "_post_once",
    )
    for token in forbidden:
        assert token not in source
