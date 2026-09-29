from pathlib import Path

PAGE = Path("pages/6_AutoTrader_POC.py").read_text(encoding="utf-8")
CHART = Path("autotrader_v3_regime_chart_ui_v1.py").read_text(encoding="utf-8")


def test_fleet_graphs_are_opt_in_and_market_filterable():
    assert '"v3-fleet-show-graphs"' in PAGE
    assert "value=False, key=\"v3-fleet-show-graphs\"" in PAGE
    assert '"v3-fleet-graph-groups"' in PAGE
    assert "for key in selected_groups:" in PAGE
    assert "if show_graphs:" in PAGE


def test_fleet_curves_can_be_filtered_per_market():
    assert 'key=f"v3-fleet-strategies:' in PAGE
    assert "selected_strategies=tuple(selected)" in PAGE
    assert "selected_strategies: tuple[str, ...] | None = None" in CHART
    assert "pivot = pivot[visible]" in CHART


def test_fleet_links_to_v3_config_without_conflating_authority():
    assert '"pages/0_AutoTrader_V3.py"' in PAGE
    assert "dette endrer ikke SIM eller LIVE" in PAGE
