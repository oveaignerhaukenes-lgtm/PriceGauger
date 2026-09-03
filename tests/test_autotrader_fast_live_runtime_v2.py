from pathlib import Path

import autotrader_fast_live_runtime_v2 as fast
from autotrader_strategy_catalog_v2 import (
    AUTOTRADER_STRATEGIES_V2,
    MACD_1M_FLIP_STRATEGY_V2,
    STRONG_COCKTAIL_STRATEGY_V2,
    strategy_spec_v2,
)
from autotrader_strong_cocktail_shadow_v2 import (
    MACD_1M_CONTROL_STRATEGY_KEY,
    STRONG_COCKTAIL_STRATEGY_KEY,
)


def test_fast_live_strategy_keys_match_existing_shadow_comparison_keys() -> None:
    assert STRONG_COCKTAIL_STRATEGY_V2 == STRONG_COCKTAIL_STRATEGY_KEY
    assert MACD_1M_FLIP_STRATEGY_V2 == MACD_1M_CONTROL_STRATEGY_KEY


def test_strong_cocktail_and_1m_macd_are_explicit_live_choices() -> None:
    keys = {item.key for item in AUTOTRADER_STRATEGIES_V2}
    assert STRONG_COCKTAIL_STRATEGY_V2 in keys
    assert MACD_1M_FLIP_STRATEGY_V2 in keys
    for key in (STRONG_COCKTAIL_STRATEGY_V2, MACD_1M_FLIP_STRATEGY_V2):
        spec = strategy_spec_v2(key)
        assert spec.can_long is True
        assert spec.can_short is True


def test_fast_request_action_preserves_close_flat_open_reversal_lifecycle() -> None:
    assert fast.fast_request_action_v2("LONG", "SHORT") == "CLOSE"
    assert fast.fast_request_action_v2("SHORT", "LONG") == "CLOSE"
    assert fast.fast_request_action_v2("LONG", "FLAT") == "CLOSE"
    assert fast.fast_request_action_v2("SHORT", "FLAT") == "CLOSE"
    assert fast.fast_request_action_v2("FLAT", "LONG") == "OPEN"
    assert fast.fast_request_action_v2("FLAT", "SHORT") == "OPEN"
    assert fast.fast_request_action_v2("LONG", "LONG") is None


def test_fast_runtime_emits_requests_but_has_no_saxo_post_authority() -> None:
    source = Path("autotrader_fast_live_runtime_v2.py").read_text(encoding="utf-8")
    assert "pg_v2_autotrader_execution_requests" in source
    assert "BOOTSTRAP_NO_REPLAY" in source
    assert "NEWER_FAST_SIGNAL" in source
    assert "CLOSE -> observed FLAT -> OPEN" in source
    assert "_post(" not in source
    assert "place_order" not in source
    assert "create_order" not in source


def test_dispatch_routes_both_fast_live_strategies_to_fast_runtime() -> None:
    source = Path("autotrader_automanage_dispatch_v2.py").read_text(encoding="utf-8")
    assert "STRONG_COCKTAIL_STRATEGY_V2" in source
    assert "MACD_1M_FLIP_STRATEGY_V2" in source
    assert "run_fast_live_strategy_once_v2" in source
    assert "if enrollment.strategy_key in FAST_LIVE_STRATEGIES" in source


def test_tradingdesk_live_selector_is_catalog_driven() -> None:
    source = Path("tradingdesk_automanage_panel_v2.py").read_text(encoding="utf-8")
    assert '"LIVE-strategi"' in source
    assert "AUTOTRADER_STRATEGIES_V2" in source
