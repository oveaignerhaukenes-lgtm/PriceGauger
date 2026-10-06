from pathlib import Path


def test_tradingdesk_and_fleet_share_instance_owned_controls():
    shared=Path('autotrader_v3_instance_controls_ui_v1.py').read_text()
    desk=Path('tradingdesk_automanage_panel_v2.py').read_text()
    fleet=Path('autotrader_v3_fleet_ui_v1.py').read_text()
    assert 'save_autotrader_config_v3(desired)' in shared
    assert 'save_execution_policy_v3(desired_policy)' in shared
    assert 'render_v3_instance_controls_v1(by_id[selected]' in desk
    assert "render_v3_instance_controls_v1(item,key_prefix='fleet')" in fleet


def test_autotrader_page_is_fleet_first_not_duplicate_config_form():
    page=Path('pages/0_AutoTrader_V3.py').read_text()
    assert 'render_v3_fleet_management_v1()' in page
    assert 'save_autotrader_config_v3' not in page
    assert 'MODIFIERS_V3' not in page


def test_tradingdesk_v3_controls_live_outside_heartbeat_fragment():
    source=Path('tradingdesk_automanage_panel_v2.py').read_text()
    assert source.index('observations=_automanager_fragment_v2()') < source.index('_render_v3_controls_for_market_v1(context)')
