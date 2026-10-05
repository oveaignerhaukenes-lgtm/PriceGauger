from pathlib import Path


def test_vnext_core_does_not_import_legacy_open_close_or_margin_envelope():
    source = Path("autotrader_v2_execution_vnext_v1.py").read_text()
    forbidden = (
        "autotrader_live_open_legacy_v2",
        "autotrader_strategy_live_close_v2",
        "autotrader_margin_envelope_v2",
        "autotrader_pilot_equity_v2",
        "strategy_execution_budget_v1",
    )
    for name in forbidden:
        assert name not in source


def test_vnext_shadow_is_read_only():
    source = Path("autotrader_v2_vnext_shadow_v1.py").read_text()
    assert "place_order" not in source
    assert "trade/v2/orders" not in source
    assert "_post" not in source
