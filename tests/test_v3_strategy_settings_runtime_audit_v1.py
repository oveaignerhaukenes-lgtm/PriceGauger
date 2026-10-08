from pathlib import Path

import pytest

from autotrader_open_sizing_v2 import EntryInstrumentRulesV2
from autotrader_v3_macd_histogram_v1 import MacdHistogramConfigV3
from autotrader_v3_macd_trailing_v1 import MacdTrailingConfigV3
from autotrader_v3_registry_v1 import live_config_issues_v3
from autotrader_v3_strategy_sizing_v1 import strategy_amount_config_v3


def _rules(*, decimals: int, minimum: float, step: float, asset_type: str = "CfdOnIndex"):
    return EntryInstrumentRulesV2(
        uic=1,
        asset_type=asset_type,
        currency="USD",
        is_tradable=True,
        non_tradable_reason="None",
        amount_decimals=decimals,
        minimum_amount=minimum,
        increment_size=step,
        contract_size=1.0,
        supported_order_types=("Market",),
        amount_quantum=10.0 ** (-decimals),
        reference_minimum_amount=minimum,
        minimum_order_value=None,
    )


def test_live_capability_contract_accepts_only_currently_wired_settings():
    assert live_config_issues_v3(
        strategy_key="macd",
        timeframe="15m",
        control_mode="Manuell",
        modifiers=("reset-on-loss",),
    ) == ()
    assert live_config_issues_v3(
        strategy_key="macd-regime-histogram",
        timeframe="5m",
        regime_timeframe="15m",
        control_mode="Manuell",
        modifiers=(),
    ) == ()
    assert live_config_issues_v3(
        strategy_key="aen2-sticky-regime",
        timeframe="2m",
        regime_timeframe="15m",
        control_mode="Manuell",
        modifiers=(),
    ) == ()
    assert live_config_issues_v3(
        strategy_key="aen21-sticky-fast-exit",
        timeframe="2m",
        regime_timeframe="15m",
        control_mode="Manuell",
        modifiers=(),
    ) == ()
    assert "regime timeframe Adaptiv" in " | ".join(live_config_issues_v3(
        strategy_key="macd-regime-histogram",
        timeframe="5m",
        regime_timeframe="Adaptiv",
        control_mode="Manuell",
        modifiers=(),
    ))

    issues = live_config_issues_v3(
        strategy_key="price-macd",
        timeframe="Adaptiv",
        control_mode="God Mode",
        modifiers=("impulse", "take-profit"),
    )
    text = " | ".join(issues)
    assert "strategy price-macd is not LIVE runtime-ready" in text
    assert "timeframe Adaptiv is not LIVE runtime-ready" in text
    assert "control mode God Mode is not LIVE runtime-ready" in text
    assert "impulse" in text and "take-profit" in text


def test_tech100_like_rules_preserve_one_centilot_strategy_tranche():
    config = strategy_amount_config_v3(
        strategy_key="macd-trailing-v1",
        rules=_rules(decimals=2, minimum=0.01, step=0.01),
    )
    assert isinstance(config, MacdTrailingConfigV3)
    assert config.tranche == pytest.approx(0.01)
    assert config.max_inventory == pytest.approx(0.10)


def test_macd_regime_strategy_uses_histogram_sizing():
    config = strategy_amount_config_v3(
        strategy_key="macd-regime-histogram-v1",
        rules=_rules(decimals=2, minimum=0.01, step=0.01),
    )
    assert isinstance(config, MacdHistogramConfigV3)
    assert config.tranche == pytest.approx(0.01)


def test_aen2_uses_histogram_sizing():
    config = strategy_amount_config_v3(
        strategy_key="aen2-sticky-regime-v1",
        rules=_rules(decimals=2, minimum=0.01, step=0.01),
    )
    assert isinstance(config, MacdHistogramConfigV3)
    assert config.tranche == pytest.approx(0.01)


def test_aen21_uses_histogram_sizing():
    config = strategy_amount_config_v3(
        strategy_key="aen21-sticky-fast-exit-v1",
        rules=_rules(decimals=2, minimum=0.01, step=0.01),
    )
    assert isinstance(config, MacdHistogramConfigV3)
    assert config.tranche == pytest.approx(0.01)


def test_integer_share_product_uses_integer_strategy_tranche():
    config = strategy_amount_config_v3(
        strategy_key="macd-histogram-v1",
        rules=_rules(decimals=0, minimum=1.0, step=1.0, asset_type="Etf"),
    )
    assert isinstance(config, MacdHistogramConfigV3)
    assert config.tranche == pytest.approx(1.0)
    assert config.max_inventory == pytest.approx(10.0)


def test_amount_precision_finer_than_v3_domain_fails_closed():
    with pytest.raises(ValueError, match="finer than V3 inventory precision"):
        strategy_amount_config_v3(
            strategy_key="macd-trailing-v1",
            rules=_rules(decimals=3, minimum=0.001, step=0.001),
        )


def test_live_runtime_consumes_capability_and_instrument_settings():
    source = Path("autotrader_v3_live_runtime_v1.py").read_text(encoding="utf-8")
    assert "live_config_issues_v3(" in source
    assert "load_entry_instrument_rules_v2(" in source
    assert "strategy_amount_config_v3(" in source
    assert "config=strategy_amount_config" in source
    assert "step=Decimal(str(instrument_rules.increment_size))" in source
    assert "step=Decimal('0.01')" not in source
    assert "enforce_execution_policy_precheck_v3(" in source
