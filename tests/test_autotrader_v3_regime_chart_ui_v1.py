import pandas as pd
from autotrader_v3_regime_chart_ui_v1 import _svg_chart

def test_svg_chart_always_renders_zero_axis_and_lines():
    frame=pd.DataFrame({"a":[0.0,1.0,-.5],"b":[0.0,-1.0,.4]},index=pd.date_range("2026-01-01",periods=3,freq="min"))
    svg=_svg_chart(frame)
    assert "<svg" in svg
    assert "0%" in svg
    assert svg.count("<polyline") == 2


from autotrader_v3_regime_chart_ui_v1 import _interactive_regime_chart


def test_fleet_plotly_chart_supports_independent_axis_zoom_and_pan():
    frame = pd.DataFrame(
        {"macd-a": [0.0, 1.0, -0.5], "hunter": [0.0, -1.0, 0.4]},
        index=pd.date_range("2026-01-01", periods=3, freq="min"),
    )
    figure = _interactive_regime_chart(frame)
    assert len(figure.data) == 2
    assert figure.layout.dragmode == "pan"
    assert figure.layout.xaxis.fixedrange is False
    assert figure.layout.yaxis.fixedrange is False
    assert figure.layout.uirevision == "v3-fleet-axis-v1"
