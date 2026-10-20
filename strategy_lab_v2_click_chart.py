"""TradingView Lightweight price-chart click -> historical replay cursor.

Small, isolated enhancement to existing PAPER-only chart. No LIVE methods.
The JS trigger returns an existing 1m candle UNIX second timestamp.
"""
from __future__ import annotations
from datetime import datetime,timedelta,timezone
from typing import Sequence

import streamlit as st

from live_sim_tv_charts_v1 import _TV_LAB_JS,build_tv_candle_payload
from strategy_lab_v2_replay import utc

_FIRST="const { data, parentElement } = component;"
_SECOND="    const options={priceLineVisible:false,lastValueVisible:true,crosshairMarkerVisible:true};"
if _TV_LAB_JS.count(_FIRST)!=1 or _TV_LAB_JS.count(_SECOND)!=1:
    raise RuntimeError("Strategy Lab v2 chart renderer anchors changed")
_TV_LAB_CLICK_JS=_TV_LAB_JS.replace(
    _FIRST,
    "const { data, parentElement, setTriggerValue } = component;",
    1,
).replace(
    _SECOND,
    """    chart.subscribeClick((param) => {
      // Price chart and as-of dialogue share the same causal UTC clock.
      const timestamp = Number(param?.time);
      if (!Number.isFinite(timestamp)) return;
      const closest = (payload.candles || []).find(
        c => Number(c.time) === timestamp
      );
      if (!closest) return;
      setTriggerValue('clicked_time', Math.round(timestamp));
    });
"""+_SECOND,
    1,
)
_lab_click_component=st.components.v2.component(
    "pricegauger_strategy_lab_v2_click_cursor",
    js=_TV_LAB_CLICK_JS,isolate_styles=False,
)


def replay_cursor_from_chart_click_v2(*,points:Sequence,clicked_seconds:int)->int|None:
    """The clicked candle is the OPEN; select its *completed* 1m observation.

    Candle at 20:01 is observable at 20:02, never at the candle start.
    A click beyond replay bounds is rejected rather than snapping into future.
    """
    try:
        candle=datetime.fromtimestamp(int(clicked_seconds),tz=timezone.utc)
    except (TypeError,ValueError,OverflowError):
        return None
    point_at=candle+timedelta(minutes=1)
    for i,point in enumerate(points):
        if utc(point.at)==point_at:return i
    return None


def render_lab_v2_click_chart(bars,events,*,key:str,title:str):
    payload=build_tv_candle_payload(bars,events,title=title)
    if not payload["candles"]:
        st.info("Ingen tilgjengelige 1m-candles for grafen.")
        return None
    result=_lab_click_component(
        key=key,data={"payload":payload,"state_key":key},
        height=970,on_clicked_time_change=lambda:None,
    )
    value=getattr(result,"clicked_time",None)
    try:return int(value) if value is not None else None
    except (TypeError,ValueError):return None


__all__=["render_lab_v2_click_chart","replay_cursor_from_chart_click_v2",
         "_TV_LAB_CLICK_JS"]
