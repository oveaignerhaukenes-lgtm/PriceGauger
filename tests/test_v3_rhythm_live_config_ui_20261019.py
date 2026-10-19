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
    assert "previously_viewed=st.session_state.get(viewed_key,config.strategy_key)" in source
