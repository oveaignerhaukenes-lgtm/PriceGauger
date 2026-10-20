"""AI-assisted LIVE setups are visible next to base strategies, not hidden."""
from pathlib import Path

from autotrader_v3_ai_live_presets_v1 import (
    AI_LIVE_PRESETS_V3,PRESETS_BY_KEY_V3,
    initial_selector_key_v3,resolve_selector_draft_v3,ai_preset_selected_v3,
)
from autotrader_v3_config_v1 import AutoTraderConfigV3
from autotrader_v3_registry_v1 import (
    STRATEGIES_V3,live_config_issues_v3,
)


def test_ai_presets_have_real_live_base_routes_no_fake_strategy_names():
    keys={x.key for x in STRATEGIES_V3}
    assert len(AI_LIVE_PRESETS_V3)==2
    assert len(PRESETS_BY_KEY_V3)==len(AI_LIVE_PRESETS_V3)
    for preset in AI_LIVE_PRESETS_V3:
        assert preset.strategy_key in keys
        assert preset.selector_key not in keys
        assert "AI" in preset.label
        assert live_config_issues_v3(
            strategy_key=preset.strategy_key,
            timeframe=preset.timeframe,
            control_mode="Manuell",
            modifiers=("ai-loss-manager",),
        )==()


def test_selection_drafts_real_config_but_does_not_write():
    for preset in AI_LIVE_PRESETS_V3:
        strategy,timeframe,mods=resolve_selector_draft_v3(
            selector_key=preset.selector_key,timeframe="5m",
            modifiers=("whipsaw","ai-loss-manager"))
        assert strategy==preset.strategy_key and timeframe=="2m"
        assert mods.count("ai-loss-manager")==1
        assert mods==("whipsaw","ai-loss-manager")
        saved=AutoTraderConfigV3(
            trader_id="i",strategy_key=strategy,timeframe=timeframe,
            modifiers=mods)
        assert initial_selector_key_v3(
            strategy_key=saved.strategy_key,
            timeframe=saved.timeframe,
            modifiers=saved.modifiers,
        )==preset.selector_key
        assert ai_preset_selected_v3(preset.selector_key)


def test_base_selection_preserves_independent_toggle():
    assert resolve_selector_draft_v3(
        selector_key="macd-flip",timeframe="10m",
        modifiers=("ai-loss-manager",))==(
            "macd-flip","10m",("ai-loss-manager",))
    assert initial_selector_key_v3(
        strategy_key="macd-flip",timeframe="5m",
        modifiers=("ai-loss-manager",))=="macd-flip"
    assert initial_selector_key_v3(
        strategy_key="macd-flip",timeframe="2m",
        modifiers=())=="macd-flip"
    assert not ai_preset_selected_v3("macd-flip")


def test_fleet_and_tradingdesk_shared_editor_discoverable_ai():
    ui=Path("autotrader_v3_instance_controls_ui_v1.py").read_text()
    fleet=Path("autotrader_v3_fleet_ui_v1.py").read_text()
    desk=Path("tradingdesk_automanage_panel_v2.py").read_text()
    assert "Strategi / AI-oppsett (LIVE)" in ui
    assert "'AI Loss Manager · LIVE (styr eksisterende posisjon)'" in ui
    assert "resolve_selector_draft_v3(" in ui
    assert "disabled=is_ai_preset" in ui
    assert "Bruk på denne instansen" in ui
    assert "render_v3_instance_controls_v1" in fleet
    assert "render_v3_instance_controls_v1" in desk
