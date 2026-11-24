"""LIVE and SIM configuration are independent for the four V3 rhythm routes."""
from pathlib import Path

import pytest

from autotrader_v3_instance_controls_ui_v1 import (
    RHYTHM_1M_CATALOG_KEYS_V3, _rhythm_selection_defaults_v3,
    _instance_save_blocked_v3,
)
from autotrader_v3_registry_v1 import live_config_issues_v3, sim_config_issues_v3


@pytest.mark.parametrize("strategy", sorted(RHYTHM_1M_CATALOG_KEYS_V3))
def test_switching_to_rhythm_presets_1m_without_saving(strategy):
    defaults = _rhythm_selection_defaults_v3("macd", strategy)
    assert defaults["timeframe"] == "1m"
    if strategy in {"rhythm-trend-1", "rhythm-trend-fractal"}:
        assert defaults["regime_timeframe"] == "15m"
    assert _rhythm_selection_defaults_v3(strategy, strategy) == {}
    assert _rhythm_selection_defaults_v3(strategy, "macd") == {}


@pytest.mark.parametrize("strategy", sorted(RHYTHM_1M_CATALOG_KEYS_V3))
def test_live_valid_rhythm_with_reset_on_loss_is_not_blocked_by_sim(strategy):
    kw = dict(strategy_key=strategy, timeframe="1m",
              control_mode="Manuell", modifiers=("reset-on-loss",),
              regime_timeframe="15m")
    live_issues=live_config_issues_v3(**kw)
    sim_issues=sim_config_issues_v3(**kw)
    assert live_issues == ()
    assert any("reset-on-loss" in issue for issue in sim_issues)
    assert not _instance_save_blocked_v3(
        live_armed=False, sim_armed=True,
        live_issues=live_issues, sim_issues=sim_issues)
    assert not _instance_save_blocked_v3(
        live_armed=True, sim_armed=True,
        live_issues=live_issues, sim_issues=sim_issues)
    assert live_config_issues_v3(**{**kw, "timeframe": "5m"})


def test_unsupported_live_config_on_armed_live_is_still_blocked():
    assert _instance_save_blocked_v3(
        live_armed=True, sim_armed=False,
        live_issues=("requires 1m",), sim_issues=())
    assert _instance_save_blocked_v3(
        live_armed=False, sim_armed=True,
        live_issues=("unsupported LIVE",), sim_issues=("unsupported SIM",))
    assert not _instance_save_blocked_v3(
        live_armed=False, sim_armed=False,
        live_issues=("unsupported LIVE",), sim_issues=("unsupported SIM",))


def test_live_button_keeps_broker_cost_and_standard_authority_guard():
    source=Path("autotrader_v3_instance_controls_ui_v1.py").read_text()
    assert "disabled=bool(live_issues or cost_blocked)" in source
    assert "set_live_enabled_v3(trader_id,True,account_id=instance.account_id)" in source
    assert "Slå LIVE av" in source
    assert "SIM-kompatibilitet (påvirker ikke LIVE)" in source
    assert "defaults = _rhythm_selection_defaults_v3(config.strategy_key, strategy)" in source


def test_single_field_edits_and_presets_are_explicit():
    from autotrader_v3_config_v1 import AutoTraderConfigV3
    from autotrader_v3_instance_controls_ui_v1 import _config_after_edit_v3
    config=AutoTraderConfigV3("a",strategy_key="macd-flip",timeframe="5m",modifiers=("account-loss-lock",))
    edited=_config_after_edit_v3(config,"timeframe","2m")
    assert edited.timeframe=="2m" and edited.modifiers==config.modifiers
    assert config.timeframe=="5m"
    preset=_config_after_edit_v3(config,"strategy","ai-live:macd-histogram:2m")
    assert preset.strategy_key=="macd-histogram" and preset.timeframe=="2m"
    assert set(preset.modifiers)=={"account-loss-lock","ai-loss-manager"}
    removed=_config_after_edit_v3(preset,"modifier:ai-loss-manager",False)
    assert removed.modifiers==config.modifiers
    rhythm=_config_after_edit_v3(config,"strategy","rhythm-trend-1")
    assert rhythm.timeframe=="1m" and rhythm.regime_timeframe=="15m"
    assert rhythm.modifiers==config.modifiers


def test_autosave_reloads_state_and_never_arms_or_saves_other_fields(monkeypatch):
    from types import SimpleNamespace
    from autotrader_v3_config_v1 import AutoTraderConfigV3
    from autotrader_v3_execution_policy_v1 import ExecutionPolicyV3
    import autotrader_v3_instance_controls_ui_v1 as ui
    config=AutoTraderConfigV3("a",strategy_key="macd-flip",timeframe="5m",modifiers=("account-loss-lock",))
    policy=ExecutionPolicyV3("a",300,80)
    configs=[]; policies=[]
    monkeypatch.setattr(ui,"load_autotrader_config_v3",lambda _:config)
    monkeypatch.setattr(ui,"load_execution_policy_v3",lambda _:policy)
    monkeypatch.setattr(ui,"authority_state_v3",lambda _:SimpleNamespace(live_armed=True,sim_armed=False))
    monkeypatch.setattr(ui,"save_autotrader_config_v3",configs.append)
    monkeypatch.setattr(ui,"save_execution_policy_v3",policies.append)
    def no(*args,**kwargs): raise AssertionError("unexpected authority or audit write")
    monkeypatch.setattr(ui,"set_live_enabled_v3",no)
    monkeypatch.setattr(ui,"record_modifier_selection_changes_v3",no)
    ui._save_instance_edit_v3(trader_id="a",expected_strategy="macd-flip",field="timeframe",value="2m")
    assert len(configs)==1 and configs[0].modifiers==config.modifiers and not policies
    ui._save_instance_edit_v3(trader_id="a",expected_strategy="macd-flip",field="budget_nok",value=400)
    assert len(configs)==1 and policies[0].exposure_pct==80
    with pytest.raises(ValueError):
        ui._save_instance_edit_v3(trader_id="a",expected_strategy="macd-flip",field="timeframe",value="Adaptiv")
    with pytest.raises(ValueError):
        ui._save_instance_edit_v3(trader_id="a",expected_strategy="macd",field="timeframe",value="2m")
    assert len(configs)==1 and len(policies)==1
