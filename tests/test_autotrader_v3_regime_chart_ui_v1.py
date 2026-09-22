import pandas as pd
from autotrader_v3_regime_chart_ui_v1 import _svg_chart

def test_svg_chart_always_renders_zero_axis_and_lines():
    frame=pd.DataFrame({"a":[0.0,1.0,-.5],"b":[0.0,-1.0,.4]},index=pd.date_range("2026-01-01",periods=3,freq="min"))
    svg=_svg_chart(frame)
    assert "<svg" in svg
    assert "0%" in svg
    assert svg.count("<polyline") == 2
