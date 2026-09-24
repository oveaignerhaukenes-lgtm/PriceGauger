from autotrader_v3_modifier_settings_v1 import DEFAULTS_V3, load_modifier_settings_v3, save_modifier_settings_v3


def test_modifier_settings_defaults_and_roundtrip(tmp_path):
    db = str(tmp_path / "mods.db")
    assert load_modifier_settings_v3("t", "take-profit", db) == DEFAULTS_V3["take-profit"]
    saved = save_modifier_settings_v3("t", "take-profit", {"giveback_pct": 17.0}, db)
    assert saved["giveback_pct"] == 17.0
    assert load_modifier_settings_v3("t", "take-profit", db)["giveback_pct"] == 17.0
