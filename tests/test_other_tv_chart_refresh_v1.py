from pathlib import Path

from tradingdesk_ui.charts.lightweight.data_revision_v1 import chart_data_revision_key_v1


def test_tv_chart_revision_changes_with_plotted_points_but_not_clock():
    baseline = {"as_of": 100, "price": [{"time": 10, "value": 100}], "events": []}
    key = chart_data_revision_key_v1("tv", "Gold", baseline)
    assert key == chart_data_revision_key_v1("tv", "Gold", {**baseline, "as_of": 101})
    assert key != chart_data_revision_key_v1("tv", "Gold", {
        **baseline, "price": [{"time": 10, "value": 101}],
    })
    assert key != chart_data_revision_key_v1("tv", "Gold", {
        **baseline, "events": [{"time": 10, "target": 1}],
    })
    assert key != chart_data_revision_key_v1("tv", "Silver", baseline)
    assert "__" not in chart_data_revision_key_v1("tv", "4912__CfdOnIndex", baseline)


def test_active_tradingdesk_tv_charts_use_data_revision_keys():
    root = Path("tradingdesk_ui/charts/lightweight")
    for filename in (
        "pnl_strategy_lab_simple_v5.py", "three_trader_tv_v1.py",
        "pnl_strategy_lab_tv_v6.py",
    ):
        source = (root / filename).read_text(encoding="utf-8")
        assert "key=chart_data_revision_key_v1(" in source
    facade = Path("tradingdesk_automanage_panel_v2.py").read_text(encoding="utf-8")
    assert "render_strategy_lab_pnl_v5 as render_strategy_lab_pnl_v1" in facade
    assert "render_tradingdesk_three_trader_lab_v1(context)" in facade
