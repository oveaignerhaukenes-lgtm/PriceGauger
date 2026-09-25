from __future__ import annotations

import streamlit as st

from trading_desk_v2_context import load_trading_desk_contexts_v2
from tradingdesk_ui.charts.lightweight.direct_contract import build_lightweight_direct_live_payload_v1
from tradingdesk_ui.charts.lightweight.simple_live_v2 import render_lightweight_simple_live_v2
from tradingdesk_ui.charts.lightweight.live_test_snapshot_v1 import load_live_test_snapshot_v1


REFRESH_MS = 1000
TIMEFRAME_MINUTES = {"1m": 1, "5m": 5, "10m": 10, "15m": 15, "30m": 30, "1h": 60}

st.set_page_config(page_title="Live Chart · PriceGauger", page_icon="📈", layout="wide")
st.title("Live Chart")
st.caption("Minimal Saxo-streamtest: canonical lukkede bars + siste forming candle. Ingen forecast, AutoTrader, indikatorer eller TradingDesk-state.")

contexts = load_trading_desk_contexts_v2()
markets = [name for name, ctx in sorted(contexts.items()) if ctx.instrument is not None]
if not markets:
    st.info("Ingen aktive Saxo-instrumenter.")
    st.stop()

left, mid, right = st.columns([3, 1, 1])
market = left.selectbox("Marked", markets, key="live-chart-market")
timeframe = mid.selectbox("Tidsperiode", tuple(TIMEFRAME_MINUTES), index=1, key="live-chart-timeframe")
window_hours = right.selectbox("Vindu", (6, 12, 24, 48), index=1, key="live-chart-window")

# The chart stays mounted; only its data projection refreshes once per second.
def _load_live_payload():
    closed, forming = load_live_test_snapshot_v1(
        market=market, timeframe=timeframe, window_hours=window_hours,
        instrument=contexts[market].instrument,
    )

    payload = build_lightweight_direct_live_payload_v1(
        market=market,
        timeframe=timeframe,
        primary=closed,
        overlays={},
        overlay_mode="Normalisert %",
        indicators=None,
        indicator_names=(),
        indicator_timeframes={},
        chart_height=760,
        price_panel_share=1.0,
        trade_markers=(),
        forming_candle=forming,
    )

    return payload, closed, forming


payload, closed, forming = _load_live_payload()
render_lightweight_simple_live_v2(payload, key=f"standalone-live-chart-v1:{market}:{timeframe}")

@st.fragment(run_every=f"{REFRESH_MS}ms")
def _refresh_live_chart_data() -> None:
    latest, closed, forming = _load_live_payload()
    render_lightweight_simple_live_v2(
        latest, key=f"standalone-live-chart-v1:{market}:{timeframe}", refresh_only=True,
    )
    c1, c2, c3 = st.columns(3)
    c1.metric("Lukkede bars", len(closed))
    c2.metric("Forming", "LIVE" if forming is not None else "ingen")
    c3.metric("Refresh", "1 s")
    if forming is not None:
        st.caption(f"Saxo forming: {forming.close:g} · source {forming.source_event_at} · bucket {forming.bar_time}")
    elif closed:
        st.caption(f"Siste lukkede candle: {closed[-1].close:g} · {closed[-1].bar_time}")


_refresh_live_chart_data()
