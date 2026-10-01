from pathlib import Path
from autotrader_strategy_catalog_v2 import strategy_spec_v2


def test_extended_pyramid_catalog_no_longer_claims_shadow_only():
    spec=strategy_spec_v2("macd-a-pyr-1-30-v1")
    assert "shadow" not in spec.label.lower()
    assert "LIVE-capable" in spec.description


def test_v2_dispatch_routes_extended_pyramid_to_exact_live_adapter():
    source=Path("autotrader_automanage_dispatch_v2.py").read_text()
    assert "MACD_A_PYR_EXTENDED_LIVE_KEY" in source
    assert "run_macd_a_pyr_extended_live_once_v1" in source


def test_pyramid_live_adapter_has_no_legacy_open_worker_bypass():
    source=Path("autotrader_macd_a_pyr_live_v1.py").read_text()
    assert "pending_order(" in source
    assert "reserve(" in source
    assert "reconcile_position_v3" in source
    assert "broker.precheck(order)" in source
    assert "e.live_open_armed" in source
    assert "MAX_AMOUNT=0.20" in source
    assert "TRANCHE=0.02" in source
