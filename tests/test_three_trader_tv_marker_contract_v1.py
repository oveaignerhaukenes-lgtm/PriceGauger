from pathlib import Path


def test_three_trader_tv_retains_analysis_marker_labels_and_flat_exit_shape():
    source = (
        Path(__file__).resolve().parents[1] / "tradingdesk_ui/charts/lightweight/three_trader_tv_v1.py"
    ).read_text(encoding="utf-8")
    for label in (
        "Dum MACD",
        "MACD-adaptiv",
        "Holistisk AI",
        "MACD + manager",
        "MACD norm",
        "MACD norm + manager",
    ):
        assert label in source
    assert "arrowUp" in source
    assert "arrowDown" in source
    assert "circle" in source
    assert "FLAT" in source
