from pathlib import Path


def test_supervisor_rule_markers_are_not_hidden_by_ai_markers() -> None:
    source = Path("tradingdesk_macd_supervisor_lab_v1.py").read_text(encoding="utf-8")
    assert 'groups.append(("AI", ai_switches, 14, False))' in source
    assert 'groups.append(("Rule", rule_switches, 10, True))' in source
    assert 'symbol = f"{base_symbol}-open" if open_marker else base_symbol' in source


def test_strategy_lab_persists_view_across_component_redraws() -> None:
    source = Path("tradingdesk_ui/charts/lightweight/pnl_strategy_lab_simple_v5.py").read_text(encoding="utf-8")
    assert "__pricegaugerStrategyLabViewV5" in source
    assert "savedView?.range" in source
    assert "rememberView(range)" in source
    assert "visibleByLabel" in source


def test_supervisor_plotly_uses_stable_uirevision() -> None:
    source = Path("tradingdesk_macd_supervisor_lab_v1.py").read_text(encoding="utf-8")
    assert 'uirevision="macd-supervisor-lab-v1"' in source
