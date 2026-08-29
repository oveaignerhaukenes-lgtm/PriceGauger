from autotrader_strategy_catalog_v2 import (
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
