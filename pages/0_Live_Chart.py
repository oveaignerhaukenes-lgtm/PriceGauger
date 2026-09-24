from __future__ import annotations

from datetime import datetime, timedelta, timezone

import streamlit as st
from streamlit_autorefresh import st_autorefresh

from realtime_market_data import RealtimeMarketDataStore
from saxo_chart_live import FormingCandleStore, forming_candle_event_age_seconds
from trading_desk import resample_bars, utc
from trading_desk_v2_context import load_trading_desk_contexts_v2
from tradingdesk_ui.charts.lightweight.direct_contract import build_lightweight_direct_live_payload_v1
from tradingdesk_ui.charts.lightweight.simple_live_v2 import render_lightweight_simple_live_v2


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

# This page deliberately owns one simple clock. A full script rerun every second
# lets us verify the Saxo -> DB/forming-store -> chart path without TradingDesk.
st_autorefresh(interval=REFRESH_MS, limit=None, key="standalone-live-chart-clock-v1")

ctx = contexts[market]
instrument = ctx.instrument
store = RealtimeMarketDataStore()
forming_store = FormingCandleStore()
now = datetime.now(timezone.utc)
raw = store.load_range(market=market, start=now - timedelta(hours=int(window_hours)), end=now, limit=20000)
closed = resample_bars(raw, timeframe=timeframe)

forming = None
try:
    candidate = forming_store.load(market=market)
except Exception:
    candidate = None

if (
    candidate is not None
    and str(candidate.uic) == str(instrument.provider_instrument_id)
    and candidate.asset_type == instrument.asset_type
    and (forming_candle_event_age_seconds(candidate) or 0.0) <= 8.0
):
    minutes = TIMEFRAME_MINUTES[timeframe]
    if minutes == 1:
        forming = candidate
    else:
        current_at = datetime.fromisoformat(str(candidate.bar_time).replace("Z", "+00:00"))
        bucket_seconds = minutes * 60
        bucket_epoch = int(current_at.timestamp()) - (int(current_at.timestamp()) % bucket_seconds)
        bucket_at = datetime.fromtimestamp(bucket_epoch, tz=timezone.utc)
        bucket_raw = [
            item for item in raw
            if bucket_at <= utc(item.bar_time) < current_at
        ]
        open_price = float(bucket_raw[0].open) if bucket_raw else float(candidate.open)
        highs = [float(x.high) for x in bucket_raw] + [float(candidate.high)]
        lows = [float(x.low) for x in bucket_raw] + [float(candidate.low)]
        from saxo_chart_live import FormingCandle1m
        forming = FormingCandle1m(
            market=candidate.market, bar_time=bucket_at.isoformat(),
            open=open_price, high=max(highs), low=min(lows), close=float(candidate.close),
            volume=candidate.volume, provider=candidate.provider, uic=int(candidate.uic),
            asset_type=candidate.asset_type, symbol=candidate.symbol,
            delayed_by_minutes=candidate.delayed_by_minutes,
            source_event_at=candidate.source_event_at, updated_at=candidate.updated_at,
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

render_lightweight_simple_live_v2(payload, key=f"standalone-live-chart-v1:{market}:{timeframe}")

c1, c2, c3 = st.columns(3)
c1.metric("Lukkede bars", len(closed))
c2.metric("Forming", "LIVE" if forming is not None else "ingen")
c3.metric("Refresh", "1 s")
if forming is not None:
    st.caption(f"Saxo forming: {forming.close:g} · source {forming.source_event_at} · bucket {forming.bar_time}")
elif closed:
    st.caption(f"Siste lukkede candle: {closed[-1].close:g} · {closed[-1].bar_time}")
