from autotrader_v3_registry_v1 import STRATEGIES_V3
from autotrader_v3_strategy_registry_v1 import STRATEGIES_V3 as RUNTIME


def test_catalog_runtime_ready_entries_resolve_to_real_runtime_adapters():
    for spec in STRATEGIES_V3:
        if spec.runtime_ready:
            assert spec.runtime_key in RUNTIME


def test_catalog_does_not_claim_unimplemented_strategies_are_runtime_ready():
    specs={x.key:x for x in STRATEGIES_V3}
    assert specs["macd"].runtime_key == "macd-trailing-v1"
    assert specs["macd"].runtime_ready
    assert specs["macd-stoch-v1"].runtime_ready
    assert specs["macd-histogram"].runtime_ready
    assert specs["macd-regime-histogram"].runtime_ready
    assert specs["aen2-sticky-regime"].runtime_ready
    assert specs["aen21-sticky-fast-exit"].runtime_ready
    assert specs["vwap-regime-histogram"].runtime_ready
    assert not specs["price-macd"].runtime_ready
    assert not specs["price-stoch"].runtime_ready
    assert not specs["sfl"].runtime_ready
