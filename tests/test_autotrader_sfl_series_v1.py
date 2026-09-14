from pathlib import Path


def test_sfl_materializer_uses_vectorized_series_bridge() -> None:
    materializer = Path("autotrader_strategy_series_materializer_v1.py").read_text(encoding="utf-8")
    source = Path("autotrader_sfl_series_v1.py").read_text(encoding="utf-8")
    assert "from autotrader_sfl_series_v1 import SFL_SERIES_VERSION_V1, load_sfl_series_v1" in materializer
    assert '.resample(' in source
    assert '.ewm(span=12' in source
    assert '.ewm(span=26' in source
    assert '.ewm(span=9' in source
    assert 'SFL_TIMEFRAMES_V1' in source
    assert 'closed_bars_v2' not in source
    assert 'macd_observations_v2' not in source


def test_sfl_vectorized_clock_uses_only_completed_timeframe_buckets() -> None:
    source = Path("autotrader_sfl_series_v1.py").read_text(encoding="utf-8")
    assert 'label="right", closed="left", origin="epoch"' in source
    assert 'method="ffill"' in source
