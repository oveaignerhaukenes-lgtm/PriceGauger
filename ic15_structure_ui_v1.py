"""Read-only archived BBO experiment. No LIVE settings or broker calls."""
from datetime import datetime,timedelta,timezone
from dataclasses import asdict
import streamlit as st
import plotly.graph_objects as go
from database import connect
from autotrader_impulse_catcher_replay_v1 import prepare_impulse_quotes
from autotrader_impulse_catcher_v14 import config_v14,load_settings
from ic15_structure_v1 import Structure,StructureConfig
from ic15_structure_replay_v1 import compare

@st.cache_data(ttl=60,show_spinner=False)
def archive(end,minutes):
    start=end-timedelta(minutes=minutes)
    with connect("pricegauger.db") as db:
        rows=db.execute("""SELECT quote_at,received_at,bid,ask FROM lsim_hyper_quotes_1s
            WHERE provider_uic=4912 AND asset_type='CfdOnIndex' AND quote_at>=? AND quote_at<=?
            ORDER BY quote_at LIMIT 15000""",((start-timedelta(minutes=35)).isoformat(),end.isoformat())).fetchall()
    return prepare_impulse_quotes(rows),start

def render_structure_lab(trader_id,key):
    st.subheader("Strukturfokus · v1.5 forskning")
    st.caption("Rullerende 30/10/5/2 min, bekreftede svingpunkter og LH-brudd (SHORT: speilvendt HL). 35 min oppvarming. Ingen LIVE-ruting.")
    a,b,c,d=st.columns(4)
    minutes=a.selectbox("Testperiode (min)",[15,30,60,120],index=2,key="structure:minutes")
    back=b.number_input("Minutter tilbake",min_value=0,max_value=1440,value=0,step=15,key="structure:back")
    sensitivity=c.slider("Svingfølsomhet",.5,8.,2.,step=.5,key="structure:sensitivity")
    breakout=d.slider("Bruddmargin (p)",0.,20.,1.,step=.5,key="structure:breakout")
    delay=st.slider("Antatt minste ordre-forsinkelse (s)",1.,10.,5.,step=1.,key="structure:delay")
    if not st.button("Kjør tre modeller",key="structure:run"):return
    end=datetime.now(timezone.utc).replace(second=0,microsecond=0)-timedelta(minutes=back)
    quotes,start=archive(end,minutes)
    if not quotes or quotes[-1].at<start or (end-quotes[-1].at).total_seconds()>60:
        st.warning("Ingen tilstrekkelig ferske quotes i valgt periode.");return
    side="LONG" if "-long-" in key else "SHORT"
    with connect("pricegauger.db") as db:
        cfg=config_v14(side,load_settings(db,trader_id,key))
    sc=StructureConfig(side,sensitivity,breakout)
    results=compare(quotes,cfg,sc,start=start,delay_s=delay)
    st.dataframe([asdict(x) for x in results],hide_index=True,use_container_width=True)
    geometry=Structure(sc)
    x=[];y=[];levels=[];focus=[];entry=[]
    for q in quotes:
        s=geometry.update(q.at,q.mid)
        if q.at<start:continue
        x.append(q.at.isoformat());y.append(q.mid);levels.append(s["level"]);focus.append(s["focus"])
        entry.append(q.mid if s["entry"] else None)
    fig=go.Figure()
    fig.add_trace(go.Scatter(x=x,y=y,name="Rå pris",text=focus,line=dict(color="#b0b6c0"),hovertemplate="%{y:.2f} · %{text}<extra></extra>"))
    fig.add_trace(go.Scatter(x=x,y=levels,name="Bekreftet strukturgrense",line=dict(color="#38bdf8"),connectgaps=False))
    fig.add_trace(go.Scatter(x=x,y=entry,name="Strukturtrigger",mode="markers",marker=dict(color="#16a34a",symbol="triangle-up" if side=="LONG" else "triangle-down",size=9)))
    fig.update_layout(height=420,hovermode="x unified",legend=dict(orientation="h"))
    st.plotly_chart(fig,use_container_width=True)
    st.caption("Points = realiserte indeks-poeng etter vist bid/ask, ikke kontoprofitt. Uferdige/manglende fills og oppvarming vises separat. Ingen finansiering, kurtasje eller ekstra slippage modellert. Samme data og forsinkelse for alle tre; ikke holdout-validering.")
