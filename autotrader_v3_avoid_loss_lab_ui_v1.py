"""Costed account NAV, read-only Unngå tap V1 Lab on canonical 1m price data."""
from __future__ import annotations
from datetime import datetime,timedelta,timezone

import pandas as pd
import streamlit as st

from autotrader_v3_avoid_loss_sim_v1 import (
    AvoidLossSimulationConfigV1,run_avoid_loss_sim_v1,
)
from live_sim_lab_store_v1 import lab_snapshot
from macd_nextgen_lab_ui_v1 import _recent_bars
from live_sim_tv_charts_v1 import render_lab_tv_series,render_lab_tv_candles


@st.fragment(run_every="60s")
def render_avoid_loss_lab_v1():
    st.subheader("Unngå tap V1 · netto kontoverdi")
    st.caption("RESEARCH-SIM på historiske ferdige 1m-barer. "
               "Frossen modellert inngangsmargin, MACD 2m, −1 % tapsstopp, "
               "+2 % aktiveringsgrense og 10 % tilbakefall fra gevinsttopp. "
               "Ingen Saxo-ordrer eller garanti for utførelse.")
    try:
        _,_,feeds=lab_snapshot()
    except Exception as exc:
        st.warning("Markedsdata er utilgjengelige: "+type(exc).__name__)
        return
    if not feeds:
        st.info("Venter på canonical 1m-markedsdata.")
        return
    sources={str(x["instrument_id"]):x for x in feeds}
    market=st.selectbox("Marked",list(sources),
        format_func=lambda k:sources[k]["market_name"],key="avoid:market")
    period=st.selectbox("Historikk", (1,3,7,14),index=2,
                        format_func=lambda x:f"{x} døgn",key="avoid:days")
    c1,c2,c3=st.columns(3)
    initial=c1.number_input("Startkapital (NOK)",min_value=100.,value=10000.,
                            step=1000.,key="avoid:nav")
    margin=c2.number_input("Frossen margin per trade (NOK)",min_value=10.,
                           value=1000.,step=100.,key="avoid:margin")
    notional=c3.number_input("Modellert underliggende notional (NOK)",min_value=100.,
                             value=10000.,step=1000.,key="avoid:notional")
    with st.expander("Kostnadsmodell · må kalibreres mot Saxo-fills"):
        a,b,c,d=st.columns(4)
        fee=a.number_input("Kurtasje per side (bp)",min_value=0.,value=1.,
                           step=.5,key="avoid:fee")
        spread=b.number_input("Full spread (bp)",min_value=0.,value=1.,
                           step=.5,key="avoid:spread")
        slippage=c.number_input("Slippage per side (bp)",min_value=0.,value=.5,
                           step=.5,key="avoid:slippage")
        carry=d.number_input("Finansiering per døgn (bp)",min_value=0.,value=1.,
                           step=.5,key="avoid:carry")
    params=(market,period,initial,margin,notional,fee,spread,slippage,carry)
    if st.button("Kjør Unngå tap · NAV-test",key="avoid:run",type="primary"):
        try:
            recent=pd.Timestamp(sources[market]["last_bar_time"])
            if recent.tzinfo is None: recent=recent.tz_localize("UTC")
            else: recent=recent.tz_convert("UTC")
            end=min(datetime.now(timezone.utc),
                    (recent+pd.Timedelta(minutes=1)).to_pydatetime())
            start=end-timedelta(days=period)
            bars=_recent_bars(int(market),(start-timedelta(days=3)).isoformat(),
                              end.isoformat())
            # Use only requested period; warmup is supplied by the early bars
            # so MACD starts without hindsight on selected performance window.
            prepared=[x for x in bars if
                pd.Timestamp(getattr(x.point,"bar_time")).tz_convert("UTC")>=
                pd.Timestamp(start-timedelta(hours=6),tz="UTC")]
            cfg=AvoidLossSimulationConfigV1(
                initial_nav_nok=initial,margin_per_trade_nok=margin,
                notional_per_trade_nok=notional,commission_bps_per_side=fee,
                full_spread_bps=spread,slippage_bps_per_side=slippage,
                daily_financing_bps=carry)
            with st.spinner("Beregner MACD 2m og netto margin-P/L på hvert 1m-lys…"):
                report=run_avoid_loss_sim_v1(prepared,config=cfg)
            st.session_state["avoid:report"]=report
            st.session_state["avoid:bars"]=bars
            st.session_state["avoid:params"]=params
        except Exception as exc:
            st.error(f"Simuleringen kunne ikke gjennomføres: {type(exc).__name__}: {exc}")
            return
    report=st.session_state.get("avoid:report")
    if report is None:
        st.info("Trykk «Kjør» for å starte testen på historiske 1m-data.")
        return
    if st.session_state.get("avoid:params")!=params:
        st.warning("Parametrene er endret. Kjør testen igjen.")
        return
    a,b,c,d=st.columns(4)
    a.metric("Sluttkapital",f"{report.final_nav_nok:,.0f} kr",
             f"{report.net_pct:+.2f} %")
    b.metric("Maks drawdown",f"{report.max_drawdown_pct:.2f} %")
    c.metric("Fullførte handler",len(report.trades))
    d.metric("Modellerte kostnader",f"{report.total_costs_nok:,.2f} kr")
    frame=pd.DataFrame(report.equity,columns=["Tid","Netto NAV (NOK)"])
    frame["Tid"]=pd.to_datetime(frame["Tid"],utc=True)
    render_lab_tv_series(frame.set_index("Tid").sort_index(),
                         key=f"avoid:equity:{market}",
                         title="Unngå tap V1 · netto NOK-kontoverdi")
    if report.trades:
        st.dataframe(pd.DataFrame([{
            "Start":x.entry_at,"Slutt":x.exit_at,
            "Retning":"LONG" if x.direction>0 else "SHORT",
            "Inngangspris":round(x.entry_price,4),
            "Utgangspris":round(x.exit_price,4),
            "Netto P/L NOK":round(x.net_pnl_nok,2),
            "Topp P/L NOK":round(x.peak_pnl_nok,2),
            "Årsak":x.reason,
        } for x in report.trades]),hide_index=True,use_container_width=True)
    st.caption("Modellen bruker konservativt intrabar-utfall, faktisk 1m-OHLC og "
               "modellerte kostnader i NOK. Manglende prisbarer fylles ikke inn. "
               "Slippage kan i virkeligheten være større enn antatt. "
               "Historisk syntetisk NAV er IKKE kontoens faktiske Saxo-P/L.")
