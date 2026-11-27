from datetime import datetime,timedelta,timezone
from pathlib import Path
from types import SimpleNamespace
from signal_lab_native_charts_v1 import ic14_payload,dsp_payload,indicator_payload,diagnostics_payload
from tradingdesk_ui.charts.lightweight.renderer import _LIGHTWEIGHT_LIVE_JS

T=datetime(2026,11,27,tzinfo=timezone.utc)
def rows():
    return [dict(at=T+timedelta(seconds=i),mid=100+i,target="LONG" if i==1 else "FLAT",
        decision="QUALIFIED_IMPULSE_V14" if i==1 else "CONFIRMED_EXIT" if i==2 else None,
        entry_price=101.,normal_price=99.,urgent_price=95.,entry_ratio=1.2,atr=3.,
        raw=1.,processed=.5,gains=(.5,),gap=False) for i in (0,1,2,12)]

def test_native_payload_preserves_signal_times_and_missing_data():
    p=ic14_payload(rows(),key="x",side="LONG")
    assert p["seconds_visible"] and p["vertical_touch_drag"]
    assert [x["time"] for x in p["markers"]]==[int(T.timestamp())+1,int(T.timestamp())+2]
    assert p["markers"][0]["color"]=="#38bdf8"
    assert p["markers"][1]["shape"]=="square"
    assert p["primary_line"][3]=={"time":int(T.timestamp())+3}
    assert p["primary_line"][-1]["value"]==112.
    assert {"hold","entry_price","normal_price","urgent_price"}<={x["role"] for x in p["lines"]}

def test_dsp_and_diagnostics_have_synchronized_panes():
    p=dsp_payload(rows(),key="dsp",stages=[SimpleNamespace(kind="gate")],labels={"gate":"Gate"})
    assert p["pane_order"]==["price","velocity","gain"]
    assert p["lines"][-1]["data"][0]["value"]==.5
    assert dsp_payload(rows(),key="dsp",stages=[],labels={})["pane_order"]==["price","velocity"]
    assert diagnostics_payload(rows(),key="diag")["pane_order"]==["price","exit"]
    assert indicator_payload(rows(),key="atr",indicator="atr",label="ATR")["primary_line"][0]["value"]==3.

def test_renderer_opt_in_touch_and_line_mode_and_compact_inspector():
    assert "vertTouchDrag: Boolean(payload.vertical_touch_drag)" in _LIGHTWEIGHT_LIVE_JS
    assert "secondsVisible: Boolean(payload.seconds_visible)" in _LIGHTWEIGHT_LIVE_JS
    assert "lineMode ? chart.addSeries(LWC.LineSeries" in _LIGHTWEIGHT_LIVE_JS
    source=Path("autotrader_v3_instance_inspection_v1.py").read_text()
    assert '"height":420,"vertical_touch_drag":True' in source
    assert '"price_panel_share":.43' in source
    for name in ("autotrader_ic14_ui.py","signal_dsp_lab_ui_v1.py"):
        assert "render_lightweight_live_chart_v1(" in Path(name).read_text()
