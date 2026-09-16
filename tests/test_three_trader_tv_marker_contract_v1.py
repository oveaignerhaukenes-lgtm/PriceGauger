from pathlib import Path


def test_three_trader_tv_retains_all_three_marker_labels():
    source = (Path(__file__).resolve().parents[1] / "tradingdesk_ui/charts/lightweight/three_trader_tv_v1.py").read_text(encoding="utf-8")
    for label in ("Dum MACD", "MACD-adaptiv", "Holistisk AI"):
        assert label in source
    assert "arrowUp" in source
    assert "arrowDown" in source
