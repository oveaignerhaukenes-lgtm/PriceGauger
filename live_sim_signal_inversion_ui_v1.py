"""MACD signal inversion research on the same actual canonical candles.

Deliberately read-only: this panel reports synchronized idealized paper
counterfactuals, NOT realized Saxo fill economics and not a LIVE strategy.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

from live_sim_lab_store_v1 import lab_snapshot
from macd_nextgen_lab_ui_v1 import _recent_bars
from live_sim_signal_inversion_v1 import (
    INVERSION_VERSION, run_inversion_experiment, PERMITTED_MINUTES,
)
from live_sim_tv_charts_v1 import render_lab_tv_series


@st.fragment(run_every="60s")
def render_signal_inversion_lab_v1():
    st.subheader("Inversjonstest · MACD / Histogram Peak Flip")
    st.caption("Forsøket bruker *samme* ferdige 1-minutts markedsbarer, "
               "samme inngangstidspunkt, samme holdetid og identisk kostnadsbelastning "
               "for original og invertert strategi. Resultatene er ikke Saxo-fills.")
    try:
        _,_,feeds=lab_snapshot()
    except Exception as exc:
        st.warning("Kan ikke lese kanonisk markedsfeed: "+type(exc).__name__)
        return
    if not feeds:
        st.info("Venter på registrerte instrumenter med canonical 1m-data.")
        return
    markets={str(x["instrument_id"]):x for x in feeds}
    selected=st.selectbox("Marked",list(markets),
         format_func=lambda x:markets[x]["market_name"],key="inverse:market")
    a,b,c=st.columns(3)
    days=a.selectbox("Historikk (dager)",(1,3,7,14),index=2,key="inverse:days")
    periods=b.multiselect("Signalperiode (minutter)",PERMITTED_MINUTES,
                          default=PERMITTED_MINUTES,key="inverse:periods")
    random_n=c.selectbox("Tilfeldige kontrollkjøringer",(10,30,100),
                         index=1,key="inverse:random")
    with st.expander("Eksponerings- og kostnadsforutsetninger"):
        x,y,z=st.columns(3)
        notional=x.slider("Modellert indeksnotional (× NAV)",
                          0.05,1.0,0.20,0.05,key="inverse:notional")
        fee=y.number_input("Kommisjon per handlet side (bp)",
                           min_value=0.0,max_value=200.0,value=8.0,step=1.0,
                           key="inverse:fee")
        spread=z.number_input("Full estimert spread (bp)",
                           min_value=0.0,max_value=100.0,value=1.0,step=0.5,
                           key="inverse:spread")
        st.caption("Kostnad per ordreleg = kommisjon + halv spread. "
                   "Ved direkte LONG→SHORT belastes to legs i begge retninger. "
                   "Ingen gearing-, finansierings-, valuta-, latency- eller "
                   "brokerbekreftelsesmodell.")
    if not periods:
        st.info("Velg minst én signalperiode.")
        return
    market=markets[selected]
    try:
        last=pd.Timestamp(market["last_bar_time"])
        if last.tzinfo is None:last=last.tz_localize("UTC")
        else:last=last.tz_convert("UTC")
        end=min(datetime.now(timezone.utc),
                 (last+pd.Timedelta(minutes=1)).to_pydatetime())
        start=end-timedelta(days=int(days))
    except Exception as exc:
        st.error("Ugyldig datoperiode: "+type(exc).__name__)
        return
    parameters=(selected,start.isoformat(),end.isoformat(),tuple(periods),
                int(random_n),float(notional),float(fee),float(spread))
    if st.button("Kjør original / invertert / tilfeldig",key="inverse:run",
                 type="primary"):
        with st.spinner("Rekalkulerer identiske fullførte candles og neste 1m-åpning…"):
            try:
                bars=_recent_bars(int(selected),
                    (start-timedelta(days=12)).isoformat(),end.isoformat())
                result=run_inversion_experiment(
                    bars,started_at=start,ended_at=end,
                    minutes=periods,notional_fraction=float(notional),
                    commission_side_bps=float(fee),
                    spread_bps=float(spread),random_controls=random_n)
                st.session_state["inverse:report"]=result
                st.session_state["inverse:parameters"]=parameters
            except Exception as exc:
                st.error("Inversjonstesten feilet: "+type(exc).__name__+
                         " · "+str(exc)[:190])
                return
    report=st.session_state.get("inverse:report")
    if report is None:
        st.info("Trykk Kjør for å beregne med gjeldende historikk og kostnader.")
        return
    if st.session_state.get("inverse:parameters")!=parameters:
        st.warning("Marked, periode eller parametere er endret. Kjør testen på nytt.")
        return
    if report.completed_bars<100:
        st.warning("Få observerte candles. Resultatene bør ikke brukes til å rangere strategier.")
    st.caption(f"{INVERSION_VERSION} · {report.start} til {report.end} · "
               f"{report.completed_bars} observerte 1m-barer · "
               f"{report.notional_fraction:.2f}× NAV eksponering · "
               f"{report.cost_per_leg_bps:g} bp per handlet side inkludert halv spread.")
    rows=[]
    for x in report.rows:
        null=next((t for t in report.placebo_medians
                   if t[0]==x.model and t[1]==x.minutes),None)
        rows.append({
            "Strategi":x.model,"TF":f"{x.minutes}m","Retning":x.variant,
            "Netto %":round(x.net_pct,3),"Brutto %":round(x.gross_pct,3),
            "Kostnadsdrag pp":round(x.cost_pct,3),
            "Max DD %":round(x.max_dd_pct,3),"Ordreendringer":x.target_switches,
            "Omsatte legs":x.traded_legs,
            "Tilfeldig median %":null[2] if null else None,
            "Tilfeldig P10/P90":f"{null[3]:+.2f} / {null[4]:+.2f}" if null else "—",
        })
    st.dataframe(pd.DataFrame(rows),hide_index=True,use_container_width=True)
    paired={}
    for x in report.rows:
        other=paired.setdefault((x.model,x.minutes),{})
        other[x.variant]=x.net_pct
    table=[]
    for (model,tf),pair in paired.items():
        original=pair.get("Original")
        inverse=pair.get("Invertert")
        if original is None or inverse is None:continue
        table.append({"Strategi":model,"TF":tf,
                      "Original netto %":round(original,3),
                      "Invertert netto %":round(inverse,3),
                      "Invertert − original pp":round(inverse-original,3)})
    st.markdown("**Samme signaler, motsatt retning**")
    st.dataframe(pd.DataFrame(table),hide_index=True,use_container_width=True)
    view=pd.DataFrame()
    for x in report.rows:
        if not x.points:continue
        column=f"{x.model} {x.minutes}m · {x.variant}"
        df=pd.DataFrame(x.points,columns=["Tid",column])
        df["Tid"]=pd.to_datetime(df["Tid"],utc=True)
        series=df.drop_duplicates(subset="Tid").set_index("Tid")[[column]]
        view=series if view.empty else view.join(series,how="outer")
    if not view.empty:
        render_lab_tv_series(view.sort_index(),
                             key="inverse:all:"+selected,
                             title="Nettoavkastning (%) · original vs invertert")
    st.caption("Den tilfeldige referansen velger LONG/SHORT for hvert av de samme "
               "hold-intervallene og trekkes for **identisk opprinnelig antall "
               "ordrelegs**. Dette er en statistisk kontroll, ikke en kjørbar "
               "strategi. Testen åpner ved neste ekte 1m-candle etter bekreftet "
               "signalcandle; direkte reversering regnes som to legs uten den "
               "ekstra Saxo-ventetiden V3 kan ha.")
    st.caption("En invers modell med bedre historikk betyr ikke at den vil "
               "fortsette å tjene. Gjenta på markeder og perioder som ikke ble "
               "brukt til å velge regel; ingen LIVE-beslutninger er koblet til panelet.")


__all__=["render_signal_inversion_lab_v1"]
