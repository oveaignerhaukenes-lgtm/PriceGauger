from pathlib import Path


def test_autotrader_page_mounts_read_only_v3_fleet_and_regime_chart():
    source = Path("pages/6_AutoTrader_POC.py").read_text(encoding="utf-8")
    assert '("V3 Fleet", "AutoManage v2", "Runtime / signal")' in source
    assert "build_fleet_read_model_v3" in source
    assert "render_autotrader_v3_fleet_preview" in source
    assert "render_v3_regime_return_chart" in source
    assert "_position_observations_v2(client)" in source
    assert "load_automanager_pnl_comparison_v2" in source
