"""Instance-local IC14 controls and read-only causal signal inspection."""
from datetime import datetime,timedelta,timezone
from collections import Counter
from dataclasses import replace
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
from database import connect
from autotrader_impulse_catcher_v14 import SLIDERS,INDICATORS,load_settings,save_settings,config_v14,preview
from autotrader_impulse_catcher_replay_v1 import prepare_impulse_quotes
from autotrader_ic14_cost_preview_v1 import estimate_costs

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
    ("entry_gain_points","Entry Gain","punkter","Pluss flytter LONG-grensen ned og SHORT-grensen opp. Minus gjør inngang vanskeligere. Gulv: minst ett punkt og én spread."),
    ("entry_confirmation_seconds","Attack · inngang","s","Hvor lenge hele inngangssignalet må være bekreftet."),
    ("minimum_hold_seconds","Hold · minimum","s","Beskytter mot normal exit. Akutt motrykk/databrudd overstyrer."),
    ("retrace_fraction","Depth · motbevegelse","%","Hvor mye av opparbeidet løp som får trekkes tilbake. Andre aktive gulv kan være større."),
    ("exit_confirmation_seconds","Release · utgang","s","Hvor lenge normal retrace må være bekreftet før exit."),
)

AUTO_CONTROLS=(("min_impulse_points","Grunnterskel","punkter",""),)+MAIN_CONTROLS[1:]

def _display_rows(data):
    display=[]
    for row in data:
        if display and (row["at"]-display[-1]["at"]).total_seconds()>8:
            display.append({"at":display[-1]["at"]+timedelta(seconds=1)})
        display.append(row)
    return pd.DataFrame(display)

def make_preview_figure(data,*,side="LONG",details=False,arms=False,original=False,research=False):
    """Price-domain overlay of the model's own observed thresholds.
    Crossing a price boundary is necessary, not sufficient, for normal signals.
    """
    df=_display_rows(data)
    x=[t.isoformat() for t in df["at"]]
    fig=go.Figure()
    def series(k):
        return df[k] if k in df else pd.Series([None]*len(df),dtype=object)
    detail=series("gate_detail").fillna("")
    fig.add_trace(go.Scatter(x=x,y=df.mid,name="Tech100 · mid",line=dict(color="#c5cbd3",width=2.2),
        connectgaps=False,customdata=list(zip(df["gate"].fillna("Datagap"),detail)),
        hovertemplate="%{y:.2f}<br>%{customdata[0]}<br>%{customdata[1]}<extra>Tech100</extra>"))
    for name,color in (("LONG","#16a34a"),("SHORT","#f59e0b")):
        fig.add_trace(go.Scatter(x=x,y=df.mid.where(df.target==name),name=name+" · HOLD",
            line=dict(color=color,width=3),connectgaps=False))
    # Distinct hues for entry and exit, including optional entry arms.
    for k,label,color,dash,width in (
        ("entry_price","ENTRY · prisgrense","#38bdf8","solid",2),
        ("normal_price","EXIT · normal","#ef4444","solid",2),
        ("urgent_price","EXIT · akutt","#a81e38","dot",1.5)):
        fig.add_trace(go.Scatter(x=x,y=series(k),name=label,line=dict(color=color,dash=dash,width=1.3 if not details else width),
            connectgaps=False,hovertemplate="%{y:.2f}<extra>"+label+"</extra>"))
    if original:
        fig.add_trace(go.Scatter(x=x,y=series("entry_base_price"),name="Entry · uten Gain",line=dict(color="#9ca3af",dash="dot",width=1),connectgaps=False,hovertemplate="%{y:.2f}<extra>Uten Gain · samme arm</extra>"))
    if arms:
        for k,label in (("entry_fast_price","Entry · rask arm"),("entry_slow_price","Entry · treg arm")):
            fig.add_trace(go.Scatter(x=x,y=series(k),name=label,line=dict(color="#7dd3fc",dash="dot",width=1),connectgaps=False))
    entry=df[df.decision=="QUALIFIED_IMPULSE_V14"]
    exits=df[df.decision.notna() & (df.decision!="QUALIFIED_IMPULSE_V14")]
    for subset,name,symbol,color in ((entry,"ENTRY","triangle-up" if side=="LONG" else "triangle-down","#38bdf8"),
                                     (exits,"EXIT","x","#ef4444")):
        fig.add_trace(go.Scatter(x=[t.isoformat() for t in subset["at"]],y=subset.mid,mode="markers",name=name,
            marker=dict(symbol=symbol,size=13,color=color,line=dict(color="#111827",width=1)),text=subset.decision,hovertemplate="%{text}<br>%{y:.2f}<extra></extra>"))
    # Amber marks price ticks where entry confirmation is running.
    cand=df[df.gate=="ENTRY_CONFIRM"]
    fig.add_trace(go.Scatter(x=[t.isoformat() for t in cand["at"]],y=cand.mid,mode="markers",name="Attack · venter",
        customdata=list(zip(cand["entry_confirm_elapsed"],cand["entry_confirm_required"])),
        marker=dict(symbol="circle-open",color="#eab308",size=6),hovertemplate="Attack: %{customdata[0]:.1f}/%{customdata[1]} s<extra></extra>"))
    rejected=df[series("entry_rejected").eq(True)]
    fig.add_trace(go.Scatter(x=[t.isoformat() for t in rejected["at"]],y=rejected.mid,mode="markers",name="Avbrutt attack",
        customdata=list(zip(rejected["entry_reject_elapsed"],rejected["entry_reject_reason"])),
        marker=dict(symbol="x",color="#eab308",size=7),hovertemplate="Avbrutt etter %{customdata[0]:.1f} s<br>%{customdata[1]}<extra></extra>"))
    fig.update_xaxes(type="date",showgrid=False)
    fig.update_yaxes(title=None,fixedrange=False,tickformat=".0f",nticks=6,automargin=True)
    fig.update_xaxes(tickformat="%H:%M:%S",nticks=5,automargin=True)
    fig.update_layout(height=440,hovermode="closest",margin=dict(l=4,r=4,t=12,b=4),
        showlegend=details,legend=dict(orientation="h",yanchor="bottom",y=1.02,x=0),dragmode="zoom")
    if research:
        fig.add_annotation(xref="paper",yref="paper",x=0,y=1,text="EKSPERIMENT · ingen LIVE-ruting",showarrow=False,font=dict(color="#eab308",size=12),xanchor="left",yanchor="top")
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

def make_indicator_figure(data,indicator,cfg):
    df=_display_rows(data)
    y=df[indicator] if indicator in df else [None]*len(df)
    fig=go.Figure(go.Scatter(x=[t.isoformat() for t in df["at"]],y=y,
        name=NAMES.get(indicator,"ATR"),line=dict(color="#38bdf8"),connectgaps=False))
    if indicator!="atr":
        threshold=getattr(cfg,indicator+"_threshold",0.)
        for v in set((threshold,-threshold)):
            fig.add_hline(y=v,line_dash="dot",line_color="#eab308")
    fig.update_layout(height=180,margin=dict(l=6,r=6,t=8,b=6),showlegend=False)
    fig.update_xaxes(type="date",tickformat="%H:%M:%S")
    return fig

def render_ic14(trader_id,key,*,prefix):
    st.markdown("**Impulse Catcher v1.4 · signalmixer**")
    st.caption("Juster parameterfanene under grafen. Kun eksplisitt lagring endrer LIVE-innstillinger.")
    with connect("pricegauger.db") as db:
        saved=load_settings(db,trader_id,key)
    root=f"{prefix}:ic14:{trader_id}:{key}"
    draft_key=root+":draft"
    # Independent draft survives optional panel visibility. No saved settings
    # change when a panel is closed or a display option is toggled.
    values={**saved,**st.session_state.get(draft_key,{})}
    chart_col,view_col=st.columns([5,1.3])
    chart_slot=chart_col.container()
    with view_col:
        st.markdown("**Visning**")
        minutes=st.selectbox("Periode (min)",[1,2,3,5,15,30,60],index=4,key=root+":minutes")
        back=st.number_input("Minutter tilbake",min_value=0,max_value=1440,value=0,step=1,key=root+":back-min")
        arms=st.checkbox("Begge entry-armer",key=root+":arms")
        details=st.checkbox("Full tegnforklaring",key=root+":legend")
        original=st.checkbox("Original entry-grense",key=root+":original")
        research=st.checkbox("Fri kurve · research",key=root+":research",help="Fjern minimumsgulvet kun i forhåndsvisningen. Kan ikke lagres til LIVE.")
        free_gain=st.slider("Fri Gain (punkter)",-200.,200.,0.,step=.5,key=root+":free-gain") if research else None
        if research:st.warning("Kun eksperiment. Lagring er sperret.")
    cost_slot=st.container()
    main_tab,entry_tab,exit_tab,atr_tab,ind_tab,auto_tab,cost_tab=st.tabs(["Mixer","Entry","Hold / Exit","ATR","Indikatorer","Auto","Kostnader"])
    delay=cost_tab.slider("Antatt utførelsesforsinkelse per side (s)",0.,10.,3.,step=1.,key=root+":cost-delay")
    extra=cost_tab.number_input("Ekstra rundturkostnad (indekspoeng)",min_value=0.,max_value=100.,value=0.,step=.5,key=root+":cost-extra")
    cost_tab.caption("Spread måles ved hypotetiske utførelser, ikke fra en fast sats. Ekstra kostnad kan inkludere slippage/gebyrer som ikke er innebygd i bid/ask.")
    # Auto is a local draft operation. Never save or alter account authority.
    from autotrader_ic14_auto_v1 import propose_ic14
    auto_key=root+":auto"
    a,b=auto_tab.columns([1,3])
    if a.button("Auto · siste time",key=root+":auto-analyze",help="Mål siste times impuls, spread og retracement. Ingen LIVE-endring før separat lagring."):
        try:
            clock=datetime.now(timezone.utc)
            quotes,_=load_preview_quotes(60,clock)
            proposal=propose_ic14(quotes,now=clock,side="LONG" if "-long-" in key else "SHORT",current=values)
            st.session_state[auto_key]=proposal
        except Exception as exc:
            st.session_state.pop(auto_key,None)
            auto_tab.warning("Auto: "+(str(exc) if isinstance(exc,ValueError) else "Data utilgjengelig: "+type(exc).__name__))
    proposal=st.session_state.get(auto_key)
    if proposal is not None:
        ev=proposal.evidence
        b.caption(f"{ev['quotes']} quotes · median spread {ev['spread']:.2f} p · median {ev['window_s']}s-bevegelse {ev['median_move']:.2f} p · retningsimpuls P85 {ev['directional_p85']:.2f} p")
        auto_tab.caption(f"Måleperiode: {ev['start']} – {ev['end']} · {ev['runs']} avsluttede løp · {ev['recovered_pullbacks']} gjeninnhentede retraces. Hold/Depth/Release beholdes ved for få relevante observasjoner.")
        auto_tab.dataframe([{"Kontroll":label.split(" · ")[0],
            "Nå":round(values[name]*100) if unit=="%" else values[name],
            "Forslag":round(proposal.settings[name]*100) if unit=="%" else proposal.settings[name],
            "Enhet":unit} for name,label,unit,_ in AUTO_CONTROLS],
            hide_index=True,use_container_width=True)
        if auto_tab.button("Bruk forslag i forhåndsvisning",key=root+":auto-apply"):
            for name,_,unit,_ in AUTO_CONTROLS:
                values[name]=proposal.settings[name]
                if unit=="%":
                    st.session_state[f"{root}:{name}:pct"]=int(round(values[name]*100))
                else:
                    st.session_state[f"{root}:{name}"]=values[name]
            st.session_state[draft_key]=dict(values)
            st.session_state.pop(auto_key,None)
        auto_tab.caption("Statistisk signaltilpasning, ikke profittoptimalisering. Attack er en heuristikk fra valgt impulsvindu; øvrige prisfiltre kan fortsatt dominere terskelen. Ingen automatisk lagring.")
    def control(name,host=st,label=None,help=None,percent=False):
        lo,hi,step,_=SLIDERS[name]
        if percent:
            v=host.slider(label or LABELS[name],int(round(lo*100)),int(round(hi*100)),
                int(round(values[name]*100)),step=int(round(step*100)),format="%d%%",key=f"{root}:{name}:pct",help=help)
            values[name]=v/100
        else:
            values[name]=host.slider(label or LABELS[name],lo,hi,values[name],step=step,key=f"{root}:{name}",help=help)
    cols=main_tab.columns(5)
    for col,(name,label,unit,help) in zip(cols,MAIN_CONTROLS):
        control(name,col,label+(" ("+unit+")" if unit!="%" else ""),help,percent=unit=="%")
    main_tab.caption("Entry Gain ↑ = mer følsom · Attack ↑ = tregere entry · Hold ↑ = mindre tidlig exit · Depth ↑ = mer retrace · Release ↑ = tregere normal exit. Auto justerer grunnterskelen; Gain er din manuelle trim.")
    with entry_tab:
        names=("min_impulse_points","fast_window","slow_window","relative_impulse_multiple","minimum_directional_efficiency","maximum_spread_points","spread_impulse_multiple")
        cols=st.columns(3)
        for i,name in enumerate(names):
            control(name,cols[i%3])
    with exit_tab:
        cols=st.columns(3)
        for i,name in enumerate(("exhaustion_seconds","minimum_retrace_points","exit_noise_multiple","urgent_retrace_points","cooldown_seconds")):
            control(name,cols[i%3])
    with atr_tab:
        cols=st.columns(3)
        for i,name in enumerate(("atr_period","atr_entry_multiple","atr_exit_multiple")):
            control(name,cols[i])
        st.caption("0 = av. ATR utvider prisgrensene ved høyere volatilitet. Ferdige 5s-bøtter.")
        atr_plot=st.container()
    with ind_tab:
        selected_ind=st.selectbox("Indikator",tuple(NAMES),format_func=lambda k:NAMES[k],key=root+":indicator-edit")
        ind=selected_ind
        selected=[p for p in ("entry","hold","exit") if ind in values[p+"_indicators"]]
        phases=st.multiselect("Bruk ved",["entry","hold","exit"],default=selected,
            format_func=str.upper,key=f"{root}:{ind}:phases")
        for phase in ("entry","hold","exit"):
            old=[v for v in values[phase+"_indicators"] if v!=ind]
            values[phase+"_indicators"]=[v for v in INDICATORS if v in old or (v==ind and phase in phases)]
        cols=st.columns(4 if ind=="macd" else 2)
        if ind=="macd":
            for i,(name,label2) in enumerate((("macd_fast","MACD · rask (ticks)"),("macd_slow","MACD · treg (ticks)"),("macd_signal","MACD · signal (ticks)"),("macd_threshold","Histogram · terskel"))):
                control(name,cols[i],label=label2)
        else:
            control(ind+"_period",cols[0],label="Periode (ticks)")
            if ind!="structure":control(ind+"_threshold",cols[1],label="Retningsterskel")
        st.caption("ENTRY: alle valgte må støtte retningen. HOLD: én i medgang kan utsette normal exit. EXIT: valgte tilgjengelige indikatorer må være i motgang.")
        indicator_plot=st.container()
    st.session_state[draft_key]=dict(values)
    active=[NAMES[i]+" ("+"/".join(p.upper() for p in ("entry","hold","exit") if i in values[p+"_indicators"])+")"
            for i in INDICATORS if any(i in values[p+"_indicators"] for p in ("entry","hold","exit"))]
    if values["atr_entry_multiple"] or values["atr_exit_multiple"]:
        active.append("ATR")
    main_tab.caption("Aktive indikatorfiltre: "+(", ".join(active) if active else "ingen ekstra")+" · alle innstillinger beholdes ved bytte av fane.")
    try:
        cfg=config_v14("LONG" if "-long-" in key else "SHORT",values)
    except ValueError as exc:
        st.warning(str(exc));return
    if research:
        cfg=replace(cfg,entry_gain_points=free_gain,research_unclamped_entry=True)
    end=datetime.now(timezone.utc).replace(second=0,microsecond=0)-timedelta(minutes=back)
    quotes,start=load_preview_quotes(minutes,end)
    full_trace=preview(quotes,cfg) if quotes else []
    trace=[r for r in full_trace if r["at"]>=start]
    if trace:
        chart_slot.plotly_chart(make_preview_figure(trace,side=cfg.side,arms=arms,details=details,original=original,research=research),use_container_width=True,key=root+":preview",config={"displayModeBar":False,"scrollZoom":False})
        chart_slot.caption("▲/▼ blå: ENTRY-signal · × rød: EXIT-signal · grå: pris · blå linje: entry-grense · rød linje: exit · grønn/oransje: HOLD · gul: Attack.")
        report=estimate_costs(quotes,full_trace,side=cfg.side,start=start,end=start+timedelta(minutes=minutes),delay_s=delay,extra_points=extra)
        with cost_slot:
            st.markdown("**Historisk kostnadsestimat · samme signaler som grafen**")
            a,b,c,d,e=st.columns(5)
            a.metric("Fullførte PAPER-handler",f"{len(report.trades)} / {report.signals}")
            b.metric("Brutto signal (p)",f"{report.gross:+.1f}")
            c.metric("Spread (p)",f"{report.spread:.1f}")
            d.metric("Forsinkelsesdrag (p)",f"{report.delay_drag:+.1f}")
            e.metric("Netto PAPER (p)",f"{report.net:+.1f}" if report.trades else "—")
            st.caption(f"Median observert spread: {report.median_spread:.2f} p · {report.wins}/{len(report.trades)} netto positive · {delay:g}s antatt forsinkelse per side · {report.coverage:.0%} sekunddekning." if report.median_spread is not None else "Ingen spreadobservasjoner.")
            if report.skipped or report.incomplete or report.carry_in or report.coverage<.8:
                st.warning(f"Ufullstendig scenario: {report.skipped} signalpar uten gjennomførbare priser, {report.incomplete} uferdige signaler, posisjon fra før perioden: {report.carry_in}. Ikke en full portefølje-replay.")
            st.caption("PAPER på historiske signaler, ingen garanti for fremtidig handelsfrekvens eller gevinst. Faktiske fills, kontoregler og ordrekvote er ikke simulert. Ekstra kostnad trekkes kun fra fullførte scenariohandler.")
        with cost_tab:
            st.caption(f"Ekstra kostnader totalt: {extra*len(report.trades):.2f} p. Positivt forsinkelsesdrag betyr tapt gevinst, negativt betyr bedre kurs.")
            st.dataframe([{"Forsinkelse (s)":lag,"Fullførte":len(test.trades),"Brutto (p)":round(test.gross,2),"Spread (p)":round(test.spread,2),"Netto (p)":round(test.net,2) if test.trades else None,"Utelatt":test.skipped+test.incomplete} for lag in sorted({0.,3.,6.,delay}) for test in (estimate_costs(quotes,full_trace,side=cfg.side,start=start,end=start+timedelta(minutes=minutes),delay_s=lag,extra_points=extra),)],hide_index=True,use_container_width=True)
            if report.trades:
                st.dataframe([dict(entry=t.entry_signal,exit=t.exit_signal,brutto_p=t.signal_gross,spread_p=t.spread,forsinkelse_p=t.delay_drag,netto_p=t.net) for t in report.trades],hide_index=True,use_container_width=True)
        indicator_plot.plotly_chart(make_indicator_figure(trace,selected_ind,cfg),use_container_width=True,key=root+":indicator-meter")
        atr_plot.plotly_chart(make_indicator_figure(trace,"atr",cfg),use_container_width=True,key=root+":atr-meter")
        latest=trace[-1]
        st.caption("Signalstatistikk for valgt periode. Trykk på et punkt for detaljer.")
        attempts=[r for r in trace if r.get("entry_rejected")]
        entries=sum(r.get("decision")=="QUALIFIED_IMPULSE_V14" for r in trace)
        reasons=Counter(r["entry_reject_reason"] for r in attempts)
        counts=Counter(r.get("threshold_source") for r in trace if r.get("threshold_source"))
        st.caption(f"Perioden: {entries} entry-signaler · {len(attempts)} avbrutte Attack. "+("Hyppigste sperrer: "+", ".join(f"{k} ({v})" for k,v in reasons.most_common(3)) if reasons else ""))
        if counts:
            st.caption("Dominerende entry-terskel: "+", ".join(f"{k} ({100*v/sum(counts.values()):.0f} %)" for k,v in counts.most_common()))
        e,x,h=st.columns(3)
        def pts(v):return "—" if v is None else f"{v:.2f}"
        e.metric("Entry-grense",pts(latest.get("entry_price")))
        x.metric("Normal exit-grense",pts(latest.get("normal_price")))
        h.metric("Hold igjen (s)",pts(latest.get("hold_remaining")))
        st.caption("Siste signalstatus: "+latest["gate"]+" · "+(latest.get("gate_detail") or "Se graf"))
        if latest.get("entry_confirm_elapsed") is not None and latest["gate"]=="ENTRY_CONFIRM":
            required=latest["entry_confirm_required"]
            st.progress(min(1.,latest["entry_confirm_elapsed"]/max(1,required)),text=f"Attack {latest['entry_confirm_elapsed']:.1f}/{required} s")
        if latest.get("threshold_source"):
            st.caption(f"Aktiv impulsterskel: {latest['entry_threshold']:.2f} p · grunnterskel {latest['entry_base_threshold']:.2f} p · Gain faktisk {latest['entry_gain_applied']:+.2f} p · {latest['threshold_source']} · {latest['entry_window']}s arm")
        with st.expander("Detaljert signalmeter",expanded=False):
            st.plotly_chart(make_diagnostics_figure(trace),use_container_width=True,key=root+":meters")
        st.caption(f"{len(trace)} ekte 1s BBO-observasjoner. FLAT ved oppvarming; signalrespons, ikke Saxo-fills, regime-/modifier-simulering eller P/L.")
    else:
        st.info("Ingen registrerte quotes i valgt periode.")
    if st.button("Lagre IC v1.4",key=root+":save",disabled=research or values==saved):
        with connect("pricegauger.db") as db:
            save_settings(db,trader_id,key,values)
        st.success("Innstillinger lagret for denne instansen. Neste LIVE-syklus leser dem.")
