from pathlib import Path

def test_materializer_includes_v3_macd_trailing_shadow_series():
    source = Path("autotrader_strategy_series_materializer_v1.py").read_text(encoding="utf-8")
    assert "load_macd_trailing_shadow_series_v3" in source
    assert "macd_trailing" in source
    assert "MACD_TRAILING_SERIES_VERSION_V3" in source
