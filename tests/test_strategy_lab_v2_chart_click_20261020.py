"""Chart click-to-scrub: only an actually present closed candle can shift AI as-of."""
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from pathlib import Path

from strategy_lab_v2_click_chart import (
    replay_cursor_from_chart_click_v2,_TV_LAB_CLICK_JS,
)

BASE=datetime(2026,10,20,21,tzinfo=timezone.utc)
POINTS=tuple(SimpleNamespace(at=BASE+timedelta(minutes=x)) for x in range(1,15))


def test_clicked_open_timestamp_targets_its_completed_bar():
    assert replay_cursor_from_chart_click_v2(
        points=POINTS,clicked_seconds=int(BASE.timestamp()))==0
    assert replay_cursor_from_chart_click_v2(
        points=POINTS,clicked_seconds=int(
            (BASE+timedelta(minutes=10)).timestamp()))==10
    assert replay_cursor_from_chart_click_v2(
        points=POINTS,clicked_seconds=int(
            (BASE-timedelta(minutes=1)).timestamp()))is None
    assert replay_cursor_from_chart_click_v2(
        points=POINTS,clicked_seconds=int(
            (BASE+timedelta(minutes=15)).timestamp()))is None


def test_browser_injects_click_into_existing_price_chart_not_broker_controls():
    assert "_TV_LAB_JS" in Path("strategy_lab_v2_click_chart.py").read_text()
    assert "chart.subscribeClick((param)" in _TV_LAB_CLICK_JS
    assert "setTriggerValue('clicked_time'" in _TV_LAB_CLICK_JS
    assert "payload.candles" in _TV_LAB_CLICK_JS
    assert "trade_action" not in Path("strategy_lab_v2_click_chart.py").read_text()
    source=Path("pages/0_Strategy_Lab_V2.py").read_text()
    assert "render_lab_v2_click_chart(" in source
    assert "replay_cursor_from_chart_click_v2(" in source
    assert 'st.session_state["slab2:pending_chart_cursor"]' in source
    assert 'st.session_state["slab2:cursor"]=int(pending_click)' in source
    assert 'st.session_state["slab2:last_handled_chart_click"]' in source
    assert "Vis hele prisforløpet for å kunne klikke frem/tilbake" in source
    assert "AI mottar fremdeles kun as-of-data" in source
    assert source.index("st.session_state[\"slab2:cursor\"]=int(pending_click)")<source.index('cursor=st.slider(')
