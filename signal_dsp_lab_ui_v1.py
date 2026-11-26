"""Read-only DSP sandbox; uses the same bounded BBO archive as IC14 preview."""
from datetime import datetime,timezone,timedelta
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
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
    x=[r["at"].isoformat() for r in rows]
    fig=make_subplots(rows=3,cols=1,shared_xaxes=True,row_heights=[.45,.35,.2],
        subplot_titles=("Tech100 · rå midquote","Rå / prosessert prisendring","Gain per plugin"),vertical_spacing=.06)
    fig.add_trace(go.Scatter(x=x,y=[None if r["gap"] else r["mid"] for r in rows],name="Rå pris",
        line=dict(color="#a0a6b1"),connectgaps=False),row=1,col=1)
    fig.add_trace(go.Scatter(x=x,y=[r["raw"] for r in rows],name="Rå bevegelse",line=dict(color="#a0a6b1",width=1)),row=2,col=1)
    fig.add_trace(go.Scatter(x=x,y=[r["processed"] for r in rows],name="Prosessert",line=dict(color="#38bdf8",width=2)),row=2,col=1)
    for i,stage in enumerate(stages):
        fig.add_trace(go.Scatter(x=x,y=[r["gains"][i] if r["gains"] else None for r in rows],
            name=f"{i+1} · {LABELS[stage.kind]}"),row=3,col=1)
    fig.update_yaxes(title="Poeng/s",row=2,col=1)
    fig.update_yaxes(title="Gain",range=[0,1.1],row=3,col=1)
    fig.update_xaxes(type="date")
    fig.update_layout(height=670,hovermode="x unified",legend=dict(orientation="h"),margin=dict(l=10,r=10,t=35,b=10))
    st.plotly_chart(fig,use_container_width=True,key="dsp:plot")
    st.caption("Gate stenger små bevegelser, kompressor demper store nivåer, downward expander reduserer små nivåer gradvis. Attack/release virker på amplitudens envelope. Datagap nullstiller tilstand. Ingen syntetiske kurs eller avkastning.")
