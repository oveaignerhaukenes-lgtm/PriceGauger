from pathlib import Path


def test_simple_strategy_lab_merges_adaptive_models_into_visible_simulator_plane() -> None:
    source = Path("tradingdesk_ui/charts/lightweight/pnl_strategy_lab_simple_v5.py").read_text(encoding="utf-8")
    assert 'payload["baseline_models"] = list(payload.get("baseline_models") or []) + list(' in source
    assert 'payload.get("advanced_models") or []' in source
    assert "MACD-A" in source
    assert "SFL-1/2/5/10" in source
