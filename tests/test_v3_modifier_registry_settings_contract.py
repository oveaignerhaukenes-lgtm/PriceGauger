from autotrader_v3_modifier_settings_v1 import DEFAULTS_V3, load_modifier_settings_v3, save_modifier_settings_v3
from autotrader_v3_registry_v1 import MODIFIERS_V3


def test_every_registered_modifier_has_settings_contract():
    assert {item.key for item in MODIFIERS_V3} == set(DEFAULTS_V3)


def test_parameter_free_modifiers_do_not_crash(tmp_path):
    db_path = str(tmp_path / "v3.db")
    for key in ("normalize", "mtf-confirmation"):
        assert load_modifier_settings_v3("trader", key, db_path) == {}
        assert save_modifier_settings_v3("trader", key, {}, db_path) == {}
        assert load_modifier_settings_v3("trader", key, db_path) == {}
