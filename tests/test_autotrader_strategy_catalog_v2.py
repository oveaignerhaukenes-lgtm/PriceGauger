from autotrader_strategy_catalog_v2 import (
    AUTOMANAGER_CLASSIC_30M_TEMPLATE_V2,
    AUTOMANAGER_FAST_15M_TEMPLATE_V2,
    AUTOMANAGER_INTRABAR_30M_TEMPLATE_V2,
    AUTOMANAGER_MTF_TEMPLATE_V2,
    AUTOMANAGER_STRATEGY_TEMPLATES_V2,
    AUTOTRADER_STRATEGIES_V2,
    MACD_FLIP_SPEC_V2,
    MACD_LONG_FLAT_SPEC_V2,
    MACD_SHORT_FLAT_SPEC_V2,
)


def test_macd_strategy_entry_direction_capabilities_are_explicit():
    assert MACD_LONG_FLAT_SPEC_V2.can_long is True
    assert MACD_LONG_FLAT_SPEC_V2.can_short is False

    assert MACD_SHORT_FLAT_SPEC_V2.can_long is False
    assert MACD_SHORT_FLAT_SPEC_V2.can_short is True

    assert MACD_FLIP_SPEC_V2.can_long is True
    assert MACD_FLIP_SPEC_V2.can_short is True


def test_experiment_templates_are_named_without_granting_live_authority():
    assert [item.label for item in AUTOMANAGER_STRATEGY_TEMPLATES_V2] == [
        "Classic 30m",
        "Fast 15m",
        "MTF 30/10/5",
        "Intrabar 30m · 1m cross",
    ]
    assert AUTOMANAGER_CLASSIC_30M_TEMPLATE_V2.live_ready is True
    assert AUTOMANAGER_FAST_15M_TEMPLATE_V2.live_ready is False
    assert AUTOMANAGER_MTF_TEMPLATE_V2.live_ready is False
    assert AUTOMANAGER_INTRABAR_30M_TEMPLATE_V2.live_ready is False
    assert AUTOMANAGER_FAST_15M_TEMPLATE_V2.shadow_running is True
    assert AUTOMANAGER_MTF_TEMPLATE_V2.shadow_running is True
    assert AUTOMANAGER_INTRABAR_30M_TEMPLATE_V2.shadow_running is False

    live_keys = {item.key for item in AUTOTRADER_STRATEGIES_V2}
    assert AUTOMANAGER_FAST_15M_TEMPLATE_V2.key not in live_keys
    assert AUTOMANAGER_MTF_TEMPLATE_V2.key not in live_keys
    assert AUTOMANAGER_INTRABAR_30M_TEMPLATE_V2.key not in live_keys
