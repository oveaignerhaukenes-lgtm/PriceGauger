"""Live-Sim Lab must always provide TV-scale navigation on all experiment panels."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from live_sim_tv_charts_v1 import (
    build_tv_series_payload,build_tv_candle_payload,
)

BASE=datetime(2026,10,15,tzinfo=timezone.utc)


def test_series_payload_is_monotonic_utc_and_deduplicated():
    idx=pd.to_datetime(["2026-10-15T10:01:00+00:00",
                        "2026-10-15T10:00:00+00:00",
                        "2026-10-15T10:01:00+00:00"],utc=True)
    frame=pd.DataFrame({"A":[1.0,0.0,2.0],"B":[float("nan"),3.0,4.0]},index=idx)
    p=build_tv_series_payload(frame,title="test")
    assert p["title"]=="test"
    assert p["series"][0]["name"]=="A"
    assert len(p["series"][0]["points"])==2
    assert [x["value"] for x in p["series"][0]["points"]]==[0.,2.]
    assert all(p["series"][0]["points"][i]["time"] <
               p["series"][0]["points"][i+1]["time"]
               for i in range(len(p["series"][0]["points"])-1))


def test_candle_payload_uses_real_ohlc_and_marks_only_valid_candle_times():
    bars=[SimpleNamespace(bar_time=(BASE+timedelta(minutes=i)).isoformat(),
        open=100+i,high=101+i,low=99+i,close=100.5+i) for i in range(3)]
    fills=[(BASE+timedelta(minutes=1),+.01,"BUY",5,101.),
           (BASE+timedelta(minutes=2),0,"FLAT",5,102.),
           (BASE+timedelta(minutes=20),-.01,"OUT_OF_RANGE",5,200.)]
    p=build_tv_candle_payload(bars,fills)
    assert len(p["candles"])==3
    assert len(p["markers"])==2
    assert [x["value"] for x in p["markers"]]==[.01,0.]
    assert p["candles"][0]["open"]==100
    assert p["candles"][1]["close"]==101.5


def test_tv_navigation_is_shared_with_all_lab_universes():
    tv=Path("live_sim_tv_charts_v1.py").read_text()
    for feature in ("lightweight-charts@5.2.1","mouseWheel:true",
        "horzTouchDrag:true","pinch:true","pressedMouseMove:true",
        "axisPressedMouseMove:true","setVisibleRange","getVisibleLogicalRange",
        "setVisibleLogicalRange","localStorage","pointermove","CandlestickSeries",
        "createSeriesMarkers","render_lab_tv_series","render_lab_tv_candles"):
        assert feature in tv
    nextgen=Path("macd_nextgen_lab_ui_v1.py").read_text()
    v2=Path("autotrader_v2_strategy_lab_ui_v1.py").read_text()
    aen=Path("aen_lab_ui_v1.py").read_text()
    lab=Path("pages/0_Live_Sim_Lab.py").read_text()
    assert "render_lab_tv_series" in nextgen
    assert "_plot_reports" in v2
    assert "render_lab_tv_candles" in aen
    assert "aen:forward:" in aen
    assert "render_lab_tv_series" in lab
    assert "st.line_chart(" not in lab
    assert "st.line_chart(" not in aen
    assert "Inversjonstest · MACD" in lab
    assert "render_signal_inversion_lab_v1()" in lab
