"""Read-only V3 per-instance trading/indicator chart and AI decision ledger.

The chart is lazy: expensive historical market reads happen only after user
opens the control. It never calls Saxo and cannot place or cancel an order.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import floor, isfinite
import logging

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from autotrader_v3_ai_decision_memory_v1 import load_ai_decisions_v1
from autotrader_v3_config_v1 import load_autotrader_config_v3
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from database import connect
from trading_desk import ChartBar, utc
from trading_desk_indicators import calculate_indicators

LOGGER = logging.getLogger("pricegauger.v3.instance_inspection")
TF_MINUTES = {"1m": 1, "2m": 2, "5m": 5, "10m": 10,
              "15m": 15, "30m": 30, "1h": 60}


def resample_complete_candles_v1(
    bars, *, timeframe_minutes: int, now: datetime,
) -> tuple[ChartBar, ...]:
    """OHLC resampling from genuine closed canonical 1m bars, no synthetic fills.

    Reject the currently forming minute, incomplete aggregated bins and bins
    with missing intermediate 1m bars; future candles cannot affect a signal.
    """
    step=int(timeframe_minutes)
    if step not in TF_MINUTES.values():
        raise ValueError("unsupported indicator timeframe")
    now_utc=utc(now)
    minute_cutoff=now_utc.replace(second=0,microsecond=0)
    buckets={}
    for bar in bars:
        at=utc(bar.bar_time)
        if at >= minute_cutoff or at.second != 0 or at.microsecond != 0:
            continue
        key=at.replace(minute=at.minute-(at.minute % step),
                       second=0,microsecond=0)
        # Align 1h (and supported subhour resolutions) to UTC start.
        buckets.setdefault(key,[]).append((at,bar))
    result=[]
    for start,raw in sorted(buckets.items()):
        raw.sort(key=lambda x:x[0])
        expected=[start+timedelta(minutes=i) for i in range(step)]
        times=[t for t,_ in raw]
        if times != expected or start+timedelta(minutes=step)>minute_cutoff:
            continue
        items=[v for _,v in raw]
        result.append(ChartBar(
            market=str(items[0].market_name),bar_time=start.isoformat(),
            open=float(items[0].open), high=max(float(x.high) for x in items),
            low=min(float(x.low) for x in items), close=float(items[-1].close),
            volume=(sum(float(x.volume) for x in items if x.volume is not None)
                    if any(x.volume is not None for x in items) else None),
        ))
    return tuple(result)


def load_instance_executions_v1(
    *, instance_id: str, account_id: str, after: datetime, limit=250,
    db_path="pricegauger.db",
) -> tuple[dict, ...]:
    """Confirmed worker execution events, NOT request attempts or manual orders."""
    try:
        with connect(db_path) as db:
            rows=db.execute("""SELECT executed_at,action,side,amount,
                inventory_before,inventory_after,request_key
                FROM autotrader_v3_execution_events
                WHERE instance_id=? AND account_id=? AND executed_at>=?
                ORDER BY executed_at DESC,request_key DESC LIMIT ?""",
                (str(instance_id),str(account_id),utc(after),
                 max(1,min(1000,int(limit))))).fetchall()
        return tuple(dict(row) for row in reversed(rows))
    except Exception as exc:
        LOGGER.warning("V3 read-only execution projection unavailable type=%s",
                       type(exc).__name__)
        return ()


def _nearest_bar_anchor(bars: tuple[ChartBar,...], timestamp: datetime):
    """Find last already-observed candle for display only, never a fill quote."""
    stamp=utc(timestamp)
    matched=None
    for b in bars:
        if utc(b.bar_time) <= stamp:
            matched=b
        else:
            break
    return matched


def build_instance_inspection_figure_v1(
    bars: tuple[ChartBar,...], executions=(), ai_decisions=(), *,
    timeframe_minutes: int,
):
    """Three synchronized panels: canonical OHLC, MACD 12/26/9, Stoch 14/3."""
    if not bars:
        raise ValueError("no completed price candles")
    indicators=calculate_indicators(bars,macd_fast=12,macd_slow=26,macd_signal=9)
    fig=make_subplots(rows=3,cols=1,shared_xaxes=True,
                      vertical_spacing=0.038,
                      row_heights=[0.54,0.24,0.22],
                      subplot_titles=("Kurs og V3-handelsmarkører",
                                      "MACD 12/26/9",
                                      "Stochastic %K/%D 14/3"))
    xx=[utc(b.bar_time) for b in bars]
    fig.add_trace(go.Candlestick(x=xx,
        open=[b.open for b in bars],high=[b.high for b in bars],
        low=[b.low for b in bars],close=[b.close for b in bars],
        increasing_line_color="#16A085",
        decreasing_line_color="#D45858",
        name="Kurs"),row=1,col=1)
    def line(points,name,color,row):
        if points:
            fig.add_trace(go.Scatter(
                x=[utc(p.bar_time) for p in points],
                y=[p.value for p in points],
                mode="lines",name=name,line={"color":color,"width":1.7},
                hovertemplate="%{x}<br>%{y:.4f}<extra>"+name+"</extra>"
            ),row=row,col=1)
    line(indicators.macd,"MACD","#328AD1",2)
    line(indicators.macd_signal,"Signal","#E0A04C",2)
    if indicators.macd_histogram:
        fig.add_trace(go.Bar(
            x=[utc(p.bar_time) for p in indicators.macd_histogram],
            y=[p.value for p in indicators.macd_histogram],
            name="Histogram",marker_color=[
                "#16986D" if p.value>=0 else "#C95757"
                for p in indicators.macd_histogram],
            opacity=.6),row=2,col=1)
    line(indicators.stochastic_k,"%K","#318BDA",3)
    line(indicators.stochastic_d,"%D","#E7A452",3)
    fig.add_hline(y=80,row=3,col=1,line_dash="dot",
                  line_color="gray",opacity=.6)
    fig.add_hline(y=20,row=3,col=1,line_dash="dot",
                  line_color="gray",opacity=.6)
    fig.update_yaxes(range=[0,100],row=3,col=1)
    for item in executions:
        when=utc(item["executed_at"])
        bar=_nearest_bar_anchor(bars,when)
        if bar is None or when > utc(bars[-1].bar_time)+timedelta(minutes=timeframe_minutes):
            continue
        side=str(item.get("side") or "").upper()
        is_flat=abs(float(item.get("inventory_after") or 0))<1e-12
        up=side=="BUY"
        marker_symbol="x" if is_flat else "triangle-up" if up else "triangle-down"
        color="#E7A452" if is_flat else "#16A085" if up else "#D45858"
        price=float(bar.close)   # visual chart anchor; never call it Saxo fill price
        title=(f"{item.get('action') or '?'} {side} "
               f"{float(item.get('amount') or 0):g} · "
               f"etter {float(item.get('inventory_after') or 0):+.3f} lot")
        fig.add_trace(go.Scatter(
            x=[when],y=[price],mode="markers",showlegend=False,
            marker={"symbol":marker_symbol,"size":12,"color":color,
                    "line":{"color":"white","width":.6}},
            hovertemplate="%{x}<br>"+title+"<br>Pris = nærmeste barclose, ikke fill<extra></extra>"
        ),row=1,col=1)
    for decision in ai_decisions:
        when=utc(decision["evaluated_at"])
        bar=_nearest_bar_anchor(bars,when)
        if bar is None or when > utc(bars[-1].bar_time)+timedelta(minutes=timeframe_minutes):
            continue
        reason=str(decision.get("reason") or "")[:400].replace("<","").replace(">","")
        fig.add_trace(go.Scatter(
            x=[when],y=[bar.close],mode="markers",showlegend=False,
            marker={"symbol":"diamond","size":14,"color":"#9E78D9",
                    "line":{"color":"white","width":1}},
            hovertemplate=(
                "%{x}<br>AI "+str(decision["mode"])+" · "+
                str(decision["action"])+"<br>"+reason+"<extra></extra>"
            )),row=1,col=1)
    fig.update_layout(
        height=630,margin={"l":10,"r":10,"t":65,"b":15},
        showlegend=True,legend={"orientation":"h","y":1.02},
        xaxis_rangeslider_visible=False,hovermode="x unified",
    )
    fig.update_xaxes(tickformat="%H:%M",showgrid=True)
    return fig


def render_v3_instance_inspection_v1(instance, *, key_prefix="fleet") -> None:
    """Embedded below each V3 instance in Fleet and TradingDesk; default idle."""
    instance_id=str(instance.instance_id)
    key=f"{key_prefix}:inspect:{instance_id}"
    if not st.toggle("Vis handelskart, MACD, Stochastic og AI-minne",
                     value=False,key=key):
        return
    config=load_autotrader_config_v3(instance_id)
    timeframe=str(config.timeframe)
    if timeframe not in TF_MINUTES:
        st.info("Grafen krever en fast signalperiode i aktiv konfigurasjon.")
        return
    tf_minutes=TF_MINUTES[timeframe]
    window=st.selectbox("Vis siste",("6 timer","12 timer","24 timer","48 timer"),
                        index=2,key=f"{key_prefix}:inspect-window:{instance_id}")
    hours={"6 timer":6,"12 timer":12,"24 timer":24,"48 timer":48}[window]
    now=datetime.now(timezone.utc)
    # Warm up MACD for 34 completed signal candles; loading is capped/lazy.
    fetch_hours=min(160,max(hours+8, hours+tf_minutes*44/60))
    try:
        source=CanonicalMarketBarStoreV2().load_instrument_range(
            instrument_id=int(instance.instrument_id),
            start=now-timedelta(hours=fetch_hours),end=now,limit=10000)
        bars=resample_complete_candles_v1(
            source,timeframe_minutes=tf_minutes,now=now)
        visible=tuple(b for b in bars if utc(b.bar_time)>=now-timedelta(hours=hours))
        executions=load_instance_executions_v1(
            instance_id=instance_id,account_id=str(instance.account_id),
            after=now-timedelta(hours=hours))
        ai_decisions=load_ai_decisions_v1(
            instance_id=instance_id,account_id=str(instance.account_id),
            instrument_id=int(instance.instrument_id),limit=50)
        if not visible:
            st.info("Ingen komplette kanoniske candles for valgt konto/instrument og periode.")
            return
        if len(bars)<35:
            st.warning("For få ferdige signalbarer til full MACD 12/26/9.")
        # Indicator warmup must include older candles, but plot only selected range.
        fig=build_instance_inspection_figure_v1(
            bars,executions=executions,ai_decisions=ai_decisions,
            timeframe_minutes=tf_minutes)
        # Keep the visual window bounded without dropping MACD warmup inputs.
        fig.update_xaxes(range=[now-timedelta(hours=hours),now])
        st.plotly_chart(fig,use_container_width=True,
                        key=f"{key_prefix}:inspect-chart:{instance_id}")
    except Exception as exc:
        LOGGER.warning("V3 inspection panel load failed instance=%s type=%s",
                       instance_id,type(exc).__name__)
        st.info("Inspeksjonsgrafen kunne ikke lastes: "+type(exc).__name__)
        return
    st.caption(
        f"Aktiv strategi: {config.strategy_key} · {timeframe}. "
        "Pris/MACD/Stoch bruker fullstendige kanoniske 1m-barer og felles TA-kode. "
        "Markørene er V3-utførelseshendelser for eksakt instans/konto; "
        "markørhøyden er siste markedsbar, IKKE bekreftet Saxo-fillpris. "
        "Historikken kan omfatte tidligere strategier på samme instans."
    )
    if executions:
        with st.expander(f"Ordrehistorikk · {len(executions)} registrerte utførelser"):
            st.dataframe(pd.DataFrame([{
                "Tid UTC":utc(x["executed_at"]),
                "Handling":x["action"],"Side":x["side"],
                "Antall":x["amount"],"Posisjon etter":x["inventory_after"],
                "Request":str(x["request_key"])[:14]
            } for x in reversed(executions)]),
            use_container_width=True,hide_index=True)
    st.markdown("**AI-beslutninger · varig etterprøvbart minne**")
    if not ai_decisions:
        st.caption("Ingen AI-inngrep dokumentert for denne instansen. "
                   "Panelet lager ikke historiske AI-forklaringer i ettertid.")
    else:
        labels=[f"{utc(x['evaluated_at']):%d.%m %H:%M:%S} UTC · "
                f"{x['mode']} {x['action']} · {x['model_id']}"
                for x in ai_decisions]
        for i,entry in enumerate(ai_decisions):
            with st.expander(labels[i],expanded=False):
                st.write(str(entry["reason"]))
                st.caption(
                    f"Strategi: {entry['strategy_key']} · "
                    f"confidence {float(entry['confidence']):.2f} · "
                    f"grunnlag {entry['evidence_as_of']} · "
                    f"snapshot SHA256 {entry['evidence_hash']}"
                )
                import json
                st.json(json.loads(entry["evidence_json"]))


__all__=["resample_complete_candles_v1",
         "load_instance_executions_v1",
         "build_instance_inspection_figure_v1",
         "render_v3_instance_inspection_v1"]
