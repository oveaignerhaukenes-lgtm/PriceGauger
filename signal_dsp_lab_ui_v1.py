"""Read-only DSP sandbox; uses the same bounded BBO archive as IC14 preview."""
from datetime import datetime,timezone,timedelta
import streamlit as st
from signal_lab_native_charts_v1 import dsp_payload
from tradingdesk_ui.charts.lightweight.renderer import render_lightweight_live_chart_v1
from autotrader_ic14_ui import load_preview_quotes
from signal_dsp_lab_v1 import Stage,process_quotes

LABELS={"gate":"Noise Gate","compressor":"Compressor","expander":"Downward Expander"}

def render_signal_dsp_lab():
    st.subheader("Signal Lab · eksperiment")
    st.warning("Kun signaleksperiment. Ingen prosessert pris sendes til LIVE, IC v1.4 eller Saxo.")
    st.caption("Inngangssignalet er prisendring per sekund (indekspoeng/s), ikke det absolutte kursnivået. Velg plugins i ønsket rekkefølge.")
    chain=st.multiselect("Plugin-kjede",tuple(LABELS),format_func=lambda k:LABELS[k],key="dsp:chain")
    st.caption("Ruting: rå BBO → "+" → ".join(LABELS[k] for k in chain)+" → forskningssignal" if chain else "Ruting: rå BBO → bypass")
    stages=[]
    for i,kind in enumerate(chain):
        with st.expander(f"{i+1} · {LABELS[kind]}",expanded=True):
            prefix=f"dsp:{i}:{kind}"
            a,b,c,d=st.columns(4)
            threshold=a.slider("Threshold (poeng/s)",.1,20.,1.,step=.1,key=prefix+":thr")
            ratio=b.slider("Ratio",1.,10.,3.,step=.25,key=prefix+":ratio") if kind!="gate" else 1.
            attack=c.slider("Attack (s)",.1,15.,1.,step=.1,key=prefix+":attack")
            release=d.slider("Release (s)",.1,30.,5.,step=.1,key=prefix+":release")
            hysteresis=b.slider("Hysterese",0.,.9,.2,step=.05,key=prefix+":hyst") if kind=="gate" else .2
            stages.append(Stage(kind,threshold,ratio,attack,release,hysteresis))
    a,b=st.columns(2)
    minutes=a.selectbox("Periode (min)",[1,2,3,5,15,30,60],index=3,key="dsp:minutes")
    back=b.number_input("Minutter tilbake",0,1440,0,step=1,key="dsp:back")
    end=datetime.now(timezone.utc).replace(second=0,microsecond=0)-timedelta(minutes=back)
    quotes,start=load_preview_quotes(minutes,end)
    if not quotes:
        st.info("Ingen ekte BBO-observasjoner i perioden.")
        return
    rows=[r for r in process_quotes(quotes,stages) if r["at"]>=start]
    if not rows:
        st.info("Ingen ekte BBO-observasjoner i perioden.")
        return
    render_lightweight_live_chart_v1(dsp_payload(rows,key="dsp:native",stages=stages,labels=LABELS),key="dsp:native")
    st.caption("Rå pris · rå/prosessert bevegelse (p/s) · gain per plugin. Dra langs prisaksen for zoom; scroll siden utenfor grafen.")
    st.caption("Gate stenger små bevegelser, kompressor demper store nivåer, downward expander reduserer små nivåer gradvis. Attack/release virker på amplitudens envelope. Datagap nullstiller tilstand. Ingen syntetiske kurs eller avkastning.")
