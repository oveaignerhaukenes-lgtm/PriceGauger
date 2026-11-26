"""Instance-local IC14 controls and read-only causal signal inspection."""
from datetime import datetime,timedelta,timezone
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
from database import connect
from autotrader_impulse_catcher_v14 import SLIDERS,INDICATORS,load_settings,save_settings,config_v14,preview
from autotrader_impulse_catcher_replay_v1 import prepare_impulse_quotes

LABELS={
 "fast_window":"Rask impulsvindu (s)","slow_window":"Langt impulsvindu (s)",
 "min_impulse_points":"Minste impuls (punkter)","relative_impulse_multiple":"Impuls / normalbevegelse",
 "minimum_directional_efficiency":"Retningseffektivitet","maximum_spread_points":"Maks spread (punkter)",
 "spread_impulse_multiple":"Impuls / spread","entry_confirmation_seconds":"Bekreft inngang (s)",
 "minimum_hold_seconds":"Minimum holdetid (s)","exhaustion_seconds":"Tid uten nytt ekstrempunkt (s)",
 "minimum_retrace_points":"Minste retrace (punkter)","retrace_fraction":"Retraceandel av løpet",
 "exit_noise_multiple":"Retrace / tickstøy","exit_confirmation_seconds":"Bekreft utgang (s)",
 "urgent_retrace_points":"Akutt motrykk (punkter)","cooldown_seconds":"Cooldown (s)",
 "atr_period":"ATR-perioder (5s-barer)","atr_entry_multiple":"ATR-multippel entry (0 = av)",
 "atr_exit_multiple":"ATR-multippel exit (0 = av)"}
NAMES=dict(velocity="Prishastighet",acceleration="Prisakselerasjon",efficiency="Retningseffektivitet",
           macd="MACD-histogram",stochastic="Stochastic",rsi="RSI",structure="HH/HL · LH/LL")

@st.cache_data(ttl=30,show_spinner=False)
def load_preview_quotes(minutes,end_bucket):
    with connect("pricegauger.db") as db:
        last=db.execute("""SELECT quote_at FROM lsim_hyper_quotes_1s
            WHERE provider_uic=4912 AND asset_type='CfdOnIndex'
            ORDER BY quote_at DESC LIMIT 1""").fetchone()
        if not last:return (),None
        end=datetime.fromisoformat(str(last["quote_at"]).replace("Z","+00:00"))
        end=min(end,end_bucket)
        start=end-timedelta(minutes=minutes)
        rows=db.execute("""SELECT quote_at,received_at,bid,ask FROM lsim_hyper_quotes_1s
            WHERE provider_uic=4912 AND asset_type='CfdOnIndex' AND quote_at>=? AND quote_at<=?
            ORDER BY quote_at LIMIT 4000""",((start-timedelta(seconds=150)).isoformat(),end.isoformat())).fetchall()
    return prepare_impulse_quotes(rows),start

def make_preview_figure(data):
    # A blank plot point makes real quote outages visible; no synthetic price.
    display=[]
    for row in data:
        if display and (row["at"]-display[-1]["at"]).total_seconds()>8:
            display.append({"at":display[-1]["at"]+timedelta(seconds=1)})
        display.append(row)
    df=pd.DataFrame(display)
    fig=make_subplots(rows=3,cols=1,shared_xaxes=True,vertical_spacing=.05,
        row_heights=[.55,.22,.23],subplot_titles=("Tech100 · signaltilstand","Entry-gate · impuls / terskel","Exit-gate · retrace og terskler"))
    fig.add_trace(go.Scatter(x=[t.isoformat() for t in df['at']],y=df.mid,name="Tech100 mid",line=dict(color="#969ca5",width=1),connectgaps=False),row=1,col=1)
    for side,color in (("LONG","#16a34a"),("SHORT","#dc2626")):
        fig.add_trace(go.Scatter(x=[t.isoformat() for t in df['at']],y=df.mid.where(df.target==side),name=side+" HOLD",
            line=dict(color=color,width=3),connectgaps=False),row=1,col=1)
    for k,label,color in (("normal_price","Normal trail","#eab308"),("urgent_price","Akutt trail","#dc2626")):
        fig.add_trace(go.Scatter(x=[t.isoformat() for t in df['at']],y=df[k],name=label,line=dict(color=color,dash="dot",width=1),connectgaps=False),row=1,col=1)
    entry=df[df.decision=="QUALIFIED_IMPULSE_V14"]
    exits=df[df.decision.notna() & (df.decision!="QUALIFIED_IMPULSE_V14")]
    for subset,name,symbol,color in ((entry,"Entry","triangle-up","#16a34a"),(exits,"Exit","x","#dc2626")):
        fig.add_trace(go.Scatter(x=[t.isoformat() for t in subset['at']],y=subset.mid,mode="markers",name=name,
            marker=dict(symbol=symbol,size=10,color=color),text=subset.decision,hovertemplate="%{text}<br>%{y}<extra></extra>"),row=1,col=1)
    fig.add_trace(go.Scatter(x=[t.isoformat() for t in df['at']],y=df.entry_ratio,name="Impuls / terskel",line=dict(color="#38bdf8"),text=df["gate"],hovertemplate="%{y:.2f} · %{text}<extra></extra>"),row=2,col=1)
    fig.add_hline(y=1,line_dash="dash",row=2,col=1)
    for k,label,color in (("retrace","Retrace","#38bdf8"),("exit_threshold","Normal terskel","#eab308"),("urgent","Akutt terskel","#dc2626")):
        fig.add_trace(go.Scatter(x=[t.isoformat() for t in df['at']],y=df[k],name=label,line=dict(color=color,width=1)),row=3,col=1)
    fig.update_xaxes(type="date")
    fig.update_layout(height=660,hovermode="x unified",margin=dict(l=12,r=8,t=40,b=15),legend=dict(orientation="h"))
    return fig

def render_ic14(trader_id,key,*,prefix):
    st.markdown("**Impulse Catcher v1.4 · signalprosessor**")
    st.caption("Endringer er forhåndsvisning frem til «Lagre IC v1.4». Ingen ordre eller automatisk arming. Akutt reversering og datagap overstyrer hold.")
    with connect("pricegauger.db") as db:
        saved=load_settings(db,trader_id,key)
    values=dict(saved)
    root=f"{prefix}:ic14:{trader_id}:{key}"
    groups=(("ENTRY",("fast_window","slow_window","min_impulse_points","relative_impulse_multiple","minimum_directional_efficiency","maximum_spread_points","spread_impulse_multiple","entry_confirmation_seconds","atr_entry_multiple")),
        ("HOLD",("minimum_hold_seconds","exhaustion_seconds")),
        ("EXIT",("minimum_retrace_points","retrace_fraction","exit_noise_multiple","exit_confirmation_seconds","urgent_retrace_points","cooldown_seconds","atr_exit_multiple")))
    for title,keys in groups:
        with st.expander(title,expanded=True):
            for name in keys:
                lo,hi,step,_=SLIDERS[name]
                values[name]=st.slider(LABELS[name],lo,hi,saved[name],step=step,key=f"{root}:{name}")
            phase=title.lower()+"_indicators"
            values[phase]=st.multiselect("Indikatorer · "+title,INDICATORS,default=saved[phase],
                format_func=lambda x:NAMES[x],key=f"{root}:{phase}")
    with st.expander("Indikatorperioder og terskler",expanded=False):
        for name in ("atr_period","velocity_period","acceleration_period","efficiency_period","stochastic_period",
                     "rsi_period","structure_period","macd_fast","macd_slow","macd_signal",
                     "velocity_threshold","acceleration_threshold","efficiency_threshold","macd_threshold",
                     "stochastic_threshold","rsi_threshold"):
            lo,hi,step,_=SLIDERS[name]
            if name=="atr_period":
                label=LABELS[name]
            elif name.startswith("macd_"):
                label="MACD · "+name.split("_",1)[1]+" (ticks)" if name!="macd_threshold" else "MACD-histogram · terskel (punkter)"
            else:
                ind,kind=name.split("_")
                label=NAMES[ind]+(" · periode (ticks)" if kind=="period" else " · terskel")
            values[name]=st.slider(label,lo,hi,saved[name],step=step,key=f"{root}:{name}")
        st.caption("Entry krever alle valgte indikatorer i medgang. Hold: én i medgang utsetter normal exit. Exit krever alle tilgjengelige valgte indikatorer i motgang; manglende data blokkerer ikke exit. RSI og Stochastic normaliseres til −1…+1; ATR er gjennomsnittlig true range på ferdige 5s-bøtter. Akutt exit overstyrer alt.")
    try:
        cfg=config_v14("LONG" if "-long-" in key else "SHORT",values)
    except ValueError as exc:
        st.warning(str(exc));return
    if st.button("Lagre IC v1.4",key=root+":save",disabled=values==saved):
        with connect("pricegauger.db") as db:
            save_settings(db,trader_id,key,values)
        st.success("Innstillinger lagret for denne instansen. Neste LIVE-syklus leser dem.")
    st.caption("Forhåndsvisning · ekte registrert 1s Saxo bid/ask · signaler, ikke fills/P&L")
    minutes=st.selectbox("Visningsperiode (minutter)",[1,2,3,5,15,30,60],index=4,key=root+":minutes")
    back=st.slider("Sluttid: minutter tilbake",0,1440,0,step=1,key=root+":back")
    end=datetime.now(timezone.utc).replace(second=0,microsecond=0)-timedelta(minutes=back)
    quotes,start=load_preview_quotes(minutes,end)
    if not quotes:
        st.info("Ingen registrerte quotes i valgt periode.");return
    trace=[r for r in preview(quotes,cfg) if r["at"]>=start]
    if not trace:
        st.info("Ingen registrerte quotes i valgt periode.");return
    st.plotly_chart(make_preview_figure(trace),use_container_width=True,key=root+":preview")
    st.caption(f"{len(trace)} observerte quotes. Oppstart FLAT med opptil 150s oppvarming; grå = ingen posisjon. Ingen broker-, regime- eller modifier-simulering; dette er signalrespons.")
