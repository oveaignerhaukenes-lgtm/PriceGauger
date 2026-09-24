import pytest

from autotrader_v3_config_v1 import AutoTraderConfigV3, load_autotrader_config_v3, save_autotrader_config_v3
from autotrader_v3_registry_v1 import CONTROL_MODES_V3, MODIFIERS_V3, STRATEGIES_V3, TIMEFRAMES_V3


def test_v3_registry_keeps_timeframe_out_of_strategy_identity():
    keys = {item.key for item in STRATEGIES_V3}
    assert "macd" in keys
    assert "macd-a" in keys
    assert not any(key.endswith("-5m") or key.endswith("-30m") for key in keys)
    assert "Adaptiv" in TIMEFRAMES_V3


def test_v3_registry_has_requested_control_layers():
    modifier_keys = {item.key for item in MODIFIERS_V3}
    assert {"impulse", "reversal", "take-profit", "whipsaw", "regime"} <= modifier_keys
    assert CONTROL_MODES_V3 == ("Manuell", "Sim-Adapt", "Overseer", "God Mode")


def test_v3_config_roundtrip(tmp_path):
    db = str(tmp_path / "v3.db")
    cfg = AutoTraderConfigV3(
        trader_id="pilot-x",
        strategy_key="macd-a",
        timeframe="Adaptiv",
        control_mode="Overseer",
        modifiers=("impulse", "whipsaw"),
    )
    save_autotrader_config_v3(cfg, db)
    assert load_autotrader_config_v3("pilot-x", db) == cfg


def test_v3_config_rejects_unknown_modifier():
    with pytest.raises(ValueError):
        AutoTraderConfigV3(trader_id="x", modifiers=("magic",))
