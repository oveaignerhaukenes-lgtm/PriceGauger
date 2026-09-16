from pathlib import Path


def test_main_live_chart_is_dst_aware_oslo_time():
    source = Path("tradingdesk_ui/charts/lightweight/direct_runtime_oslo_v2.py").read_text(encoding="utf-8")
    assert "Europe/Oslo" in source
    assert "Intl.DateTimeFormat('nb-NO'" in source
    assert "timeFormatter" in source
    assert "tickMarkFormatter" in source


def test_package_installs_oslo_direct_renderer():
    source = Path("tradingdesk_ui/charts/lightweight/__init__.py").read_text(encoding="utf-8")
    assert "render_lightweight_direct_live_oslo_v2" in source
    assert "_direct_runtime.render_lightweight_direct_live_v1 = render_lightweight_direct_live_oslo_v2" in source
