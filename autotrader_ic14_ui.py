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

# Five direct controls, not new derived settings. Existing values are preserved.
MAIN_CONTROLS=(
    ("min_impulse_points","Threshold · inngang","punkter","Høyere = større prisimpuls før entry. Spread og normalstøy kan allerede kreve mer."),
    ("entry_confirmation_seconds","Attack · inngang","s","Hvor lenge hele inngangssignalet må være bekreftet."),
    ("minimum_hold_seconds","Hold · minimum","s","Beskytter mot normal exit. Akutt motrykk/databrudd overstyrer."),
    ("retrace_fraction","Depth · motbevegelse","%","Hvor mye av opparbeidet løp som får trekkes tilbake. Andre aktive gulv kan være større."),
    ("exit_confirmation_seconds","Release · utgang","s","Hvor lenge normal retrace må være bekreftet før exit."),
)

def _display_rows(data):
    display=[]
    for row in data:
        if display and (row["at"]-display[-1]["at"]).total_seconds()>8:
            display.append({"at":display[-1]["at"]+timedelta(seconds=1)})
        display.append(row)
    return pd.DataFrame(display)

def make_preview_figure(data,*,side="LONG",details=False,arms=False):
    """Price-domain overlay of the model's own observed thresholds.
    Crossing a price boundary is necessary, not sufficient, for normal signals.
    """
    df=_display_rows(data)
    x=[t.isoformat() for t in df["at"]]
    fig=go.Figure()
    def series(k):
        return df[k] if k in df else pd.Series([None]*len(df),dtype=object)
    detail=series("gate_detail").fillna("")
    fig.add_trace(go.Scatter(x=x,y=df.mid,name="Tech100 · mid",line=dict(color="#a0a6b1",width=1.5),
        connectgaps=False,customdata=list(zip(df["gate"].fillna("Datagap"),detail)),
        hovertemplate="%{y:.2f}<br>%{customdata[0]}<br>%{customdata[1]}<extra>Tech100</extra>"))
    for name,color in (("LONG","#16a34a"),("SHORT","#f59e0b")):
        fig.add_trace(go.Scatter(x=x,y=df.mid.where(df.target==name),name=name+" · HOLD",
            line=dict(color=color,width=3),connectgaps=False))
    # Both entry and exit are red, distinguished by dashes and state.
    for k,label,color,dash,width in (
        ("entry_price","ENTRY · prisgrense","#ef4444","dash",2),
        ("normal_price","EXIT · normal","#ef4444","solid",2),
        ("urgent_price","EXIT · akutt","#a81e38","dot",1.5)):
        fig.add_trace(go.Scatter(x=x,y=series(k),name=label,line=dict(color=color,dash=dash,width=width),
            connectgaps=False,hovertemplate="%{y:.2f}<extra>"+label+"</extra>"))
    if arms:
        for k,label in (("entry_fast_price","Entry · rask arm"),("entry_slow_price","Entry · treg arm")):
            fig.add_trace(go.Scatter(x=x,y=series(k),name=label,line=dict(color="#fb7185",dash="dot",width=1),connectgaps=False))
    entry=df[df.decision=="QUALIFIED_IMPULSE_V14"]
    exits=df[df.decision.notna() & (df.decision!="QUALIFIED_IMPULSE_V14")]
    for subset,name,symbol,color in ((entry,"ENTRY","triangle-up" if side=="LONG" else "triangle-down","#16a34a"),
                                     (exits,"EXIT","x","#ef4444")):
        fig.add_trace(go.Scatter(x=[t.isoformat() for t in subset["at"]],y=subset.mid,mode="markers",name=name,
            marker=dict(symbol=symbol,size=11,color=color),text=subset.decision,hovertemplate="%{text}<br>%{y:.2f}<extra></extra>"))
    # Amber marks price ticks where entry confirmation is running.
    cand=df[df.gate=="ENTRY_CONFIRM"]
    fig.add_trace(go.Scatter(x=[t.isoformat() for t in cand["at"]],y=cand.mid,mode="markers",name="Attack · venter",
        marker=dict(symbol="circle-open",color="#eab308",size=5),hovertemplate="Entry-bekreftelse pågår<extra></extra>"))
    fig.update_xaxes(type="date",showgrid=False)
    fig.update_yaxes(title="Indekspoeng",fixedrange=False)
    fig.update_layout(height=460,hovermode="x unified",margin=dict(l=12,r=8,t=10,b=10),
        legend=dict(orientation="h",yanchor="bottom",y=1.02,x=0),dragmode="zoom")
    return fig

def make_diagnostics_figure(data):
    df=_display_rows(data)
    x=[t.isoformat() for t in df["at"]]
    fig=make_subplots(rows=2,cols=1,shared_xaxes=True,vertical_spacing=.12,
        subplot_titles=("Entry · impuls / krav","Exit · retrace (punkter)"))
    fig.add_trace(go.Scatter(x=x,y=df.entry_ratio,name="Impuls / krav",line=dict(color="#38bdf8"),text=df["gate"],
        hovertemplate="%{y:.2f} · %{text}<extra></extra>"),row=1,col=1)
    fig.add_hline(y=1,line_dash="dash",line_color="#ef4444",row=1,col=1)
    for k,label,color in (("retrace","Retrace","#38bdf8"),("exit_threshold","Normal terskel","#ef4444"),("urgent","Akutt terskel","#a81e38")):
        fig.add_trace(go.Scatter(x=x,y=df[k],name=label,line=dict(color=color,width=1)),row=2,col=1)
    fig.update_xaxes(type="date")
    fig.update_layout(height=330,hovermode="x unified",margin=dict(l=10,r=8,t=40,b=15),legend=dict(orientation="h"))
    return fig

def render_ic14(trader_id,key,*,prefix):
    st.markdown("**Impulse Catcher v1.4 · signalmixer**")
    st.caption("Juster fem hovedkontroller og se prisgrafen under. Kun eksplisitt lagring endrer LIVE-innstillinger.")
    with connect("pricegauger.db") as db:
        saved=load_settings(db,trader_id,key)
    root=f"{prefix}:ic14:{trader_id}:{key}"
    draft_key=root+":draft"
    # Independent draft survives optional panel visibility. No saved settings
    # change when a panel is closed or a display option is toggled.
    values=dict(st.session_state.get(draft_key,saved))
    # Auto is a local draft operation. Never save or alter account authority.
    from autotrader_ic14_auto_v1 import propose_ic14
    auto_key=root+":auto"
    a,b=st.columns([1,3])
    if a.button("Auto · siste time",key=root+":auto-analyze",help="Mål siste times impuls, spread og retracement. Ingen LIVE-endring før separat lagring."):
        try:
            clock=datetime.now(timezone.utc)
            quotes,_=load_preview_quotes(60,clock)
            proposal=propose_ic14(quotes,now=clock,side="LONG" if "-long-" in key else "SHORT",current=values)
            st.session_state[auto_key]=proposal
        except Exception as exc:
            st.session_state.pop(auto_key,None)
            st.warning("Auto: "+(str(exc) if isinstance(exc,ValueError) else "Data utilgjengelig: "+type(exc).__name__))
    proposal=st.session_state.get(auto_key)
    if proposal is not None:
        ev=proposal.evidence
        b.caption(f"{ev['quotes']} quotes · median spread {ev['spread']:.2f} p · median {ev['window_s']}s-bevegelse {ev['median_move']:.2f} p · retningsimpuls P85 {ev['directional_p85']:.2f} p")
        st.caption(f"Måleperiode: {ev['start']} – {ev['end']} · {ev['runs']} avsluttede løp · {ev['recovered_pullbacks']} gjeninnhentede retraces. Hold/Depth/Release beholdes ved for få relevante observasjoner.")
        st.dataframe([{"Kontroll":label.split(" · ")[0],
            "Nå":round(values[name]*100) if unit=="%" else values[name],
            "Forslag":round(proposal.settings[name]*100) if unit=="%" else proposal.settings[name],
            "Enhet":unit} for name,label,unit,_ in MAIN_CONTROLS],
            hide_index=True,use_container_width=True)
        if st.button("Bruk forslag i forhåndsvisning",key=root+":auto-apply"):
            for name,_,unit,_ in MAIN_CONTROLS:
                values[name]=proposal.settings[name]
                if unit=="%":
                    st.session_state[f"{root}:{name}:pct"]=int(round(values[name]*100))
                else:
                    st.session_state[f"{root}:{name}"]=values[name]
            st.session_state[draft_key]=dict(values)
            st.session_state.pop(auto_key,None)
        st.caption("Statistisk signaltilpasning, ikke profittoptimalisering. Attack er en heuristikk fra valgt impulsvindu; øvrige prisfiltre kan fortsatt dominere terskelen. Ingen automatisk lagring.")
    def control(name,host=st,label=None,help=None,percent=False):
        lo,hi,step,_=SLIDERS[name]
        if percent:
            v=host.slider(label or LABELS[name],int(round(lo*100)),int(round(hi*100)),
                int(round(values[name]*100)),step=int(round(step*100)),format="%d%%",key=f"{root}:{name}:pct",help=help)
            values[name]=v/100
        else:
            values[name]=host.slider(label or LABELS[name],lo,hi,values[name],step=step,key=f"{root}:{name}",help=help)
    cols=st.columns(5)
    for col,(name,label,unit,help) in zip(cols,MAIN_CONTROLS):
        control(name,col,label+(" ("+unit+")" if unit!="%" else ""),help,percent=unit=="%")
    st.caption("Threshold ↑ = større impuls · Attack ↑ = tregere entry · Hold ↑ = mindre tidlig exit · Depth ↑ = mer retrace · Release ↑ = tregere normal exit.")
    panels=st.multiselect("Legg til paneler",["Avansert ENTRY","Avansert HOLD/EXIT","ATR","Prishastighet","Prisakselerasjon","Retningseffektivitet","MACD-histogram","Stochastic","RSI","HH/HL · LH/LL"],
        key=root+":panels",placeholder="Velg bare det du vil finjustere")
    if "Avansert ENTRY" in panels:
        with st.expander("Avansert ENTRY",expanded=True):
            for name in ("fast_window","slow_window","relative_impulse_multiple","minimum_directional_efficiency","maximum_spread_points","spread_impulse_multiple"):
                control(name)
    if "Avansert HOLD/EXIT" in panels:
        with st.expander("Avansert HOLD/EXIT",expanded=True):
            for name in ("exhaustion_seconds","minimum_retrace_points","exit_noise_multiple","urgent_retrace_points","cooldown_seconds"):
                control(name)
    if "ATR" in panels:
        with st.expander("ATR · volatilitet",expanded=True):
            for name in ("atr_period","atr_entry_multiple","atr_exit_multiple"):control(name)
            st.caption("0 = av. ATR utvider prisgrensene ved høyere volatilitet. Ferdige 5s-bøtter.")
    for ind,label in NAMES.items():
        if label not in panels:continue
        with st.expander(label,expanded=True):
            selected=[p for p in ("entry","hold","exit") if ind in values[p+"_indicators"]]
            phases=st.multiselect("Bruk ved",["entry","hold","exit"],default=selected,
                format_func=str.upper,key=f"{root}:{ind}:phases")
            for phase in ("entry","hold","exit"):
                old=[v for v in values[phase+"_indicators"] if v!=ind]
                values[phase+"_indicators"]=[v for v in INDICATORS if v in old or (v==ind and phase in phases)]
            if ind=="macd":
                for name,label2 in (("macd_fast","MACD · rask (ticks)"),("macd_slow","MACD · treg (ticks)"),("macd_signal","MACD · signal (ticks)"),("macd_threshold","Histogram · terskel")):
                    control(name,label=label2)
            else:
                control(ind+"_period",label="Periode (ticks)")
                if ind!="structure":control(ind+"_threshold",label="Retningsterskel")
            st.caption("ENTRY: alle valgte må støtte retningen. HOLD: én i medgang kan utsette normal exit. EXIT: valgte tilgjengelige indikatorer må være i motgang.")
    st.session_state[draft_key]=dict(values)
    active=[NAMES[i]+" ("+"/".join(p.upper() for p in ("entry","hold","exit") if i in values[p+"_indicators"])+")"
            for i in INDICATORS if any(i in values[p+"_indicators"] for p in ("entry","hold","exit"))]
    if values["atr_entry_multiple"] or values["atr_exit_multiple"]:
        active.append("ATR")
    st.caption("Aktive indikatorfiltre: "+(", ".join(active) if active else "ingen ekstra")+" · skjulte paneler beholder innstillingene.")
    try:
        cfg=config_v14("LONG" if "-long-" in key else "SHORT",values)
    except ValueError as exc:
        st.warning(str(exc));return
    st.markdown("**Tech100 · signalrespons**")
    a,b,c=st.columns([2,2,1])
    minutes=a.selectbox("Periode (min)",[1,2,3,5,15,30,60],index=4,key=root+":minutes")
    back=b.number_input("Minutter tilbake",min_value=0,max_value=1440,value=0,step=1,key=root+":back-min")
    arms=c.checkbox("Begge entry-armer",key=root+":arms",help="Vis rask og treg prisgrense i tillegg til nærmeste.")
    end=datetime.now(timezone.utc).replace(second=0,microsecond=0)-timedelta(minutes=back)
    quotes,start=load_preview_quotes(minutes,end)
    trace=[r for r in preview(quotes,cfg) if r["at"]>=start] if quotes else []
    if trace:
        st.plotly_chart(make_preview_figure(trace,side=cfg.side,arms=arms),use_container_width=True,key=root+":preview")
        latest=trace[-1]
        st.caption("Rød stiplet: nødvendig entry-pris · rød heltrukket: normal exit · rød prikket: akutt exit. Prisgrense alene er ikke nok; Attack, Hold, Release, retning og indikatorer kan fortsatt sperre.")
        e,x,h=st.columns(3)
        def pts(v):return "—" if v is None else f"{v:.2f}"
        e.metric("Entry-grense",pts(latest.get("entry_price")))
        x.metric("Normal exit-grense",pts(latest.get("normal_price")))
        h.metric("Hold igjen (s)",pts(latest.get("hold_remaining")))
        st.caption("Siste signalstatus: "+latest["gate"]+" · "+(latest.get("gate_detail") or "Se graf"))
        with st.expander("Detaljert signalmeter",expanded=False):
            st.plotly_chart(make_diagnostics_figure(trace),use_container_width=True,key=root+":meters")
        st.caption(f"{len(trace)} ekte 1s BBO-observasjoner. FLAT ved oppvarming; signalrespons, ikke Saxo-fills, regime-/modifier-simulering eller P/L.")
    else:
        st.info("Ingen registrerte quotes i valgt periode.")
    if st.button("Lagre IC v1.4",key=root+":save",disabled=values==saved):
        with connect("pricegauger.db") as db:
            save_settings(db,trader_id,key,values)
        st.success("Innstillinger lagret for denne instansen. Neste LIVE-syklus leser dem.")
