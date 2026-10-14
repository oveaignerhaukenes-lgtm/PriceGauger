"""SIM-only AEn Core workspace: no runtime authority or Saxo mutation."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from dataclasses import replace
from types import SimpleNamespace

import pandas as pd
import streamlit as st

from aen_replay_v1 import AEnPaperConfig, FAMILIES, TIMEFRAMES, ENGINE_VERSION, replay, prepare_replay_inputs
from live_sim_lab_store_v1 import lab_snapshot
from macd_nextgen_lab_ui_v1 import _recent_bars, _plot_reports
from live_sim_tv_charts_v1 import render_lab_tv_series, render_lab_tv_candles


def _regime_contributions(report, bars, *, lookback=20):
    """Classify each return by PREVIOUS completed bars, never future outcomes."""
    closes = {str(pd.to_datetime(b.bar_time, utc=True) + pd.Timedelta(minutes=1)):
              float(b.close) for b in bars}
    ordered = sorted(closes.items())
    times = [t for t, _ in ordered]
    vals = [v for _, v in ordered]
    regimes = {}
    for i in range(lookback, len(vals)):
        history = vals[i-lookback:i]  # exclude the bar whose P/L will be scored
        displacement = history[-1] - history[0]
        travel = sum(abs(history[j] - history[j-1]) for j in range(1, len(history)))
        efficiency = abs(displacement) / travel if travel > 0 else 0
        regime = ("Sideveis" if efficiency < 0.32 else
                  "Opptrend" if displacement > 0 else "Nedtrend")
        regimes[times[i]] = regime
    prior = None
    summary = {}
    for stamp, pct, _gross, _units in report.points:
        # the signal closes at this timestamp; outcome is for the preceding bar
        regime = regimes.get(str(pd.to_datetime(stamp, utc=True)))
        if prior is not None and regime:
            slot = summary.setdefault(regime, [0, 0.0])
            slot[0] += 1
            slot[1] += pct - prior
        prior = pct
    return [{"Regime":name,"1m-barer":v[0],
             "Sum netto %-poeng (referanse)":round(v[1],4)}
            for name, v in sorted(summary.items())]


def _filled_chart(bars, report, *, market_key="AEn"):
    """Actual canonical OHLC candles plus read-only PAPER fill markers."""
    render_lab_tv_candles(
        bars, report.fills, key=f"aen:price:{market_key}",
        title=f"Pris og PAPER-fills · {report.label}",
    )


@st.fragment(run_every="60s")
def render_aen_forward_panel_v1(instrument_id: int):
    """Actual prospective, frozen cohort evidence; no backfilled leaderboard."""
    st.markdown("#### AEn Forward PAPER · registrert fra oppstart")
    st.caption("Fastlåste 1-enhetskonfigurasjoner evalueres etter hvert som nye "
               "1m-candles ferdigstilles. Ingen Saxo-ordrer, ingen historiske "
               "avkastningstall registreres som fremoverskuende resultat.")
    try:
        import json
        from aen_forward_paper_v1 import forward_snapshot
        runs,points=forward_snapshot(instrument_id=instrument_id,limit=1500)
    except Exception as exc:
        st.info("Fremoverskuende PAPER starter når SIM-workeren har "
                "initialisert kohortene: "+type(exc).__name__)
        return
    if not runs:
        st.info("Ingen AEn Forward-kohorter er registrert ennå. "
                "SIM-workeren starter dem ved neste ferdige minutt.")
        return
    view=[]
    names={}
    for run in runs:
        cfg=json.loads(run["config_json"])
        name=(cfg["family"]+" · "+str(cfg["minutes"])+"m"+
              (" AUTO" if cfg.get("adaptive") else "")+
              " · "+str(run["run_id"])[:6])
        names[run["run_id"]]=name
        view.append({
            "Strategi":name,
            "Startet UTC":run["enrolled_at"],
            "Status":run["status"],
            "Netto PAPER %":round(float(run["net_pct"]),4),
            "Brutto %":round(float(run["gross_pct"]),4),
            "Maks DD %":round(float(run["max_dd_pct"]),4),
            "Omsatte enheter":int(run["turnover_units"]),
            "Aktive enheter":int(run["units"]),
            "Siste lukket bar":run["last_bar_end"] or "Venter på fremtidige data",
        })
    st.dataframe(pd.DataFrame(view),hide_index=True,use_container_width=True)
    active_ids={row["run_id"] for row in runs if row["status"]=="ACTIVE"}
    active_points=[x for x in points if x["run_id"] in active_ids]
    if active_points:
        frame=pd.DataFrame([{
            "Tid":pd.to_datetime(x["bar_end"],utc=True),
            "Strategi":names.get(x["run_id"],x["run_id"]),
            "Netto PAPER %":float(x["net_pct"]),
        } for x in active_points])
        render_lab_tv_series(frame.pivot_table(
            index="Tid",columns="Strategi",values="Netto PAPER %",
            aggfunc="last").sort_index(),key=f"aen:forward:{instrument_id}",
            title="AEn Forward · kun aktive kohorter (%)")
    else:
        st.caption("Ingen aktive Forward-punkter ennå. Historiske avbrutte "
                   "forsøk blir ikke presentert som løpende avkastning.")
    archived=[row for row in runs if row["status"]!="ACTIVE"]
    if archived:
        with st.expander(f"Arkiv · {len(archived)} avsluttede/pausede kohorter"):
            st.dataframe(pd.DataFrame([
                {"Run":row["run_id"][:10],"Status":row["status"],
                 "Start":row["enrolled_at"],"Netto %":row["net_pct"]}
                for row in archived]),hide_index=True,use_container_width=True)
            archived_points=[x for x in points if x["run_id"] not in active_ids]
            if archived_points:
                frame=pd.DataFrame([{
                    "Tid":pd.to_datetime(x["bar_end"],utc=True),
                    "Strategi":names.get(x["run_id"],x["run_id"]),
                    "Netto PAPER %":float(x["net_pct"]),
                } for x in archived_points])
                render_lab_tv_series(frame.pivot_table(
                    index="Tid",columns="Strategi",values="Netto PAPER %",
                    aggfunc="last").sort_index(),
                    key=f"aen:forward:archive:{instrument_id}",
                    title="Historiske pausede PAPER-kohorter (%)")
    st.caption("Låst 14-dagers observasjonsvindu. 5-minutters sampling "
               "samt separate eksekveringspunkter. Fastlagte proxykostnader "
               "og syntetisk notional; ikke Saxo-verifisert P/L. "
               "Historiske replayresultater nedenfor holdes adskilt.")


def render_aen_core_lab_v1():
    st.subheader("AEn Core · Adaptive Engine")
    st.caption("Ny, isolert historisk PAPER-motor. Simulering, ikke virkelig handel. "
               "Deterministisk AUTO er ikke AI-autonomi. Ingen Saxo-ordrer eller kontotilgang.")
    try:
        _, _, feeds = lab_snapshot()
    except Exception as exc:
        st.warning("AEn kan ikke hente markedskilder: "+type(exc).__name__)
        return
    if not feeds:
        st.info("Venter på canonical 1m-markedsdata.")
        return
    sources = {str(x["instrument_id"]):x for x in feeds}
    selected = st.selectbox("AEn-marked",list(sources),
                            format_func=lambda k:sources[k]["market_name"],key="aen:market")
    market = sources[selected]
    render_aen_forward_panel_v1(int(selected))
    st.divider()
    # Each market keeps its own SIM controls within this Streamlit session.
    keybase = f"aen:{selected}:"
    if "tech" not in str(market["market_name"]).lower() or "100" not in str(market["market_name"]):
        st.info("0,01 lot er verifisert som minimum for Tech100 i dette prosjektet, "
                "men ikke for dette markedet. Enhetene her er kun syntetisk PAPER-notional.")
    a,b,c,d = st.columns(4)
    signal_tf = a.selectbox("MACD-oppløsning (min)",TIMEFRAMES,index=2,key=keybase+"signal_tf")
    structure_tf = b.selectbox("HH/HL-candles (min)",TIMEFRAMES,index=2,key=keybase+"structure_tf")
    days = c.selectbox("Analyseperiode (dager)",(1,3,7,14),index=1,key=keybase+"days")
    auto = d.toggle("AUTO timeframe",value=False,key=keybase+"auto",
                    help="Regelbasert PAPER-controller med hysterese. AI har ingen kontroll i denne versjonen.")
    capkey=keybase+"max_units"
    st.session_state.setdefault(capkey,1)
    cols = st.columns([2,1,1,2,2])
    cols[0].markdown(f"**Tillatt eksponering:** {st.session_state[capkey]} × 0,01 lot")
    if cols[1].button("↓ −1",key=keybase+"less",disabled=st.session_state[capkey]<=1):
        st.session_state[capkey]-=1
    if cols[2].button("↑ +1",key=keybase+"more",disabled=st.session_state[capkey]>=20):
        st.session_state[capkey]+=1
    scale = cols[3].toggle("Structure Scaling",value=True,key=keybase+"scale")
    impulse = cols[4].toggle("Impulse Detector",value=False,key=keybase+"impulse")
    ladder_col, pulse_col = st.columns([1,2])
    ladder = ladder_col.toggle("1m→2m→5m bekreftelse",value=False,key=keybase+"ladder",
                    help="Valgfri 0,01-lot pulsprobe, deretter én enhet på 2m og 5m bekreftelse.")
    pulse_pct = pulse_col.slider("Minst 1m-puls (%)",0.05,1.0,0.12,0.01,
                                 disabled=not ladder,key=keybase+"pulse")
    settings = st.columns(3)
    left = settings[0].number_input("Swing: venstre candles",min_value=1,max_value=8,value=2,key=keybase+"left")
    right = settings[1].number_input("Swing: bekreftelsescandles",min_value=1,max_value=8,value=2,key=keybase+"right")
    hysteresis = settings[2].slider("MACD hysterese",0.0,2.0,0.5,0.1,key=keybase+"hysteresis")
    x,y,z = st.columns(3)
    impulse_pct = x.number_input("Impulse candle (%)",min_value=0.05,max_value=5.0,
                                 value=0.30,step=0.05,disabled=not impulse,key=keybase+"impulse_pct")
    vol_factor = y.number_input("Relativt volum ×",min_value=1.0,max_value=5.0,
                                value=1.4,step=0.1,disabled=not impulse,key=keybase+"vol")
    wait_bars = z.number_input("Maks retrace-venting (min)",min_value=1,max_value=30,
                               value=3,disabled=not impulse,key=keybase+"wait")
    with st.expander("Kostnader og risikoforutsetninger",expanded=False):
        charge=st.toggle("Inkluder kostnader",value=True,key=keybase+"costs")
        f,s,notional=st.columns(3)
        fee=f.number_input("Kommisjon per side (%)",0.0,2.0,0.08,0.01,format="%.3f",
                           key=keybase+"fee",disabled=not charge)
        spread=s.number_input("Full spread (%)",0.0,1.0,0.01,0.005,format="%.3f",
                              key=keybase+"spread",disabled=not charge)
        nominal=notional.number_input("SIM-notional per 0,01 lot (× NAV)",0.01,1.0,0.20,0.01,
                                      key=keybase+"unit_exposure")
        st.caption("0,08 %/side, 0,01 % spread og notional/NAV er FORUTSETNINGER – ikke "
                   "bekreftede Saxo-priser eller reell kontraktseksponering. "
                   "Fremtidig LIVE krever instrumentspesifikk NOK-/marginmodell.")
    choices=st.multiselect("Sammenlign strategier",FAMILIES,default=FAMILIES,
                           key=keybase+"families",max_selections=4)
    if not choices:
        st.info("Velg minst én AEn-strategi.")
        return
    try:
        anchor=min(datetime.now(timezone.utc),
                   datetime.fromisoformat(str(market["last_bar_time"]).replace("Z","+00:00"))
                   +timedelta(minutes=1))
        since=anchor-timedelta(days=int(days))
        bars=_recent_bars(int(selected),(since-timedelta(days=10)).isoformat(),anchor.isoformat())
        if not bars:
            st.warning("Ingen kanoniske 1m-data for dette markedet.")
            return
        configs=[AEnPaperConfig(
            family=family,minutes=int(signal_tf),structure_minutes=int(structure_tf),
            pivot_left=int(left),pivot_right=int(right),max_units=int(st.session_state[capkey]),
            adaptive=auto,structure_scaling=scale,confirmation_ladder=ladder,
            pulse_min_pct=float(pulse_pct),impulse_enabled=impulse,
            impulse_pct=float(impulse_pct),volume_factor=float(vol_factor),
            retrace_wait_bars=int(wait_bars),hysteresis_ratio=float(hysteresis),
            unit_exposure=float(nominal),costs_enabled=charge,
            commission_side_bps=fee*100,quoted_spread_bps=spread*100
        ) for family in choices]
        prepared=prepare_replay_inputs(bars,configs[0])
        reports=[replay(cfg,bars,started_at=since,prepared=prepared) for cfg in configs]
    except Exception as exc:
        st.error("AEn replay ble avbrutt: "+type(exc).__name__+" · "+str(exc)[:180])
        return
    reports.sort(key=lambda r:(-r.return_pct,r.identity))
    st.caption(f"Felles datasett · {since:%d.%m %H:%M}–{anchor:%d.%m %H:%M} UTC · {ENGINE_VERSION}. "
               "For hver endring beregnes alle kurver på nytt. Historiske resultater er ikke forward P/L.")
    st.dataframe(pd.DataFrame([{
        "Strategi":r.label, "Netto SIM %":round(r.return_pct,3),
        "Brutto %":round(r.gross_pct,3), "Maks DD %":round(r.max_drawdown_pct,3),
        "Kostnader (% av start)":round(r.total_cost_pct,3),
        "Ordreendringer":r.executions,"Omsatte enheter":r.turnover_units,
        "Aktiv / tillatt":f"{abs(r.points[-1][3]) if r.points else 0}/{st.session_state[capkey]}",
        "Timeframe-bytter":len(r.timeframe_changes),
    } for r in reports]),hide_index=True,use_container_width=True)
    _plot_reports([SimpleNamespace(identity=r.identity,label=r.label,
                                   return_pct=r.return_pct,
                                   points=tuple((t,n,g) for t,n,g,_ in r.points))
                   for r in reports],key=f"aen:replay:{selected}")
    variants={r.label:r for r in reports}
    name=st.selectbox("Vis markedspris, SIM-fills og eksponering",list(variants),
                      key=keybase+"detail")
    focus=variants[name]
    _filled_chart(bars,focus,market_key=selected)
    if focus.points:
        exposure=pd.DataFrame([{"Tid":pd.to_datetime(t,utc=True),"Enheter":units}
                               for t,_net,_gross,units in focus.points]).set_index("Tid")
        render_lab_tv_series(exposure,key=f"aen:exposure:{selected}",
                             title="Mål-eksponering (enheter)")
    from aen_diagnostics_v1 import turnover_diagnostics
    diag=turnover_diagnostics(focus)
    st.markdown("#### Kostnads- og whipsaw-diagnose")
    m1,m2,m3,m4=st.columns(4)
    m1.metric("Omsatte enheter",diag.total_units)
    m2.metric("Flat→ny posisjon ≤2m",diag.exit_to_reentry_under_2m)
    m3.metric("Flat→ny posisjon ≤5m",diag.exit_to_reentry_under_5m)
    m4.metric("Brutto–netto %-poeng",f"{diag.estimated_cost_drag_pct:+.3f}")
    st.caption("Re-entry telles bare etter en registrert flat-posisjon; tallene "
               "forklarer mulig churn, ikke gevinst per enkeltordre.")
    with st.expander("AEn modulablasjon · like historiske data"):
        st.caption("Sammenlign basis, struktur, impuls og AUTO uten å velge "
                   "historisk beste variant som fremoverskuende vinner. "
                   "Kjøres kun når du aktiverer kontrollen.")
        if st.toggle("Beregn fem kontrollvarianter",value=False,
                     key=keybase+"ablate"):
            # Reuse module-level prepare_replay_inputs; a function-level import
            # would shadow it and raise UnboundLocalError on the main replay path.
            base=next((cfg for cfg in configs if cfg.family in focus.label), configs[0])
            common=replace(base,adaptive=False,impulse_enabled=False,
                           confirmation_ladder=False,structure_scaling=False)
            trials=[
                ("BASE · én enhet",replace(common,max_units=1)),
                ("STRUCTURE",replace(common,structure_scaling=True)),
                ("STRUCTURE + IMPULSE",replace(common,structure_scaling=True,
                                              impulse_enabled=True)),
                ("STRUCTURE + AUTO",replace(common,structure_scaling=True,
                                           adaptive=True)),
                ("FULL",base),
            ]
            results=[]
            for label,cfg in trials:
                candidate=replay(cfg,bars,started_at=since,prepared=prepared)
                d=turnover_diagnostics(candidate)
                results.append({
                    "Kontroll":label,"Netto %":round(candidate.return_pct,3),
                    "Brutto %":round(candidate.gross_pct,3),
                    "Kostnad %":round(candidate.total_cost_pct,3),
                    "Maks DD %":round(candidate.max_drawdown_pct,3),
                    "Omsatte enheter":candidate.turnover_units,
                    "Re-entry ≤5m":d.exit_to_reentry_under_5m,
                    "Timeframe-skift":len(candidate.timeframe_changes),
                })
            st.dataframe(pd.DataFrame(results),hide_index=True,
                         use_container_width=True)

    with st.expander("Walk-forward · velg på treningsdata, mål på holdout"):
        st.caption("Frosset eksperiment med 13 kandidater: 4 strategifamilier × "
                   "2/5/10m og én regelbasert AUTO 10m. Alle bruker maks 1 enhet, "
                   "samme HH/HL-periode og kostnader PÅ. Tidsrammen velges kun "
                   "på første 65 %; siste 35 % er urørt holdout.")
        st.caption("Resultatene er historisk ut-av-utvalg på én kronologisk splitt, "
                   "ikke en uavhengig fremoverskuende PAPER-måling. "
                   "Gjentatt parameterjustering på samme holdout kan overtilpasse.")
        if st.button("Kjør walk-forward på valgt tidsvindu",type="secondary",
                     key=keybase+"walkforward"):
            from aen_walk_forward_v1 import candidate_configs,evaluate_walk_forward
            with st.spinner("Sammenligner identiske kostnader, datavinduer og én-enhetsposisjoner…"):
                try:
                    split=since+(anchor-since)*0.65
                    w=evaluate_walk_forward(
                        bars,started_at=since,split_at=split,ended_at=anchor,
                        configs=candidate_configs(
                            structure_minutes=int(structure_tf),
                            unit_exposure=float(nominal),
                            commission_side_bps=float(fee)*100,
                            quoted_spread_bps=float(spread)*100,
                        ))
                    st.session_state[keybase+"walk_result"]=w
                    st.session_state[keybase+"walk_dataset"]=(since,anchor,int(structure_tf),
                                         float(nominal),float(fee),float(spread))
                except Exception as exc:
                    st.error("Walk-forward kunne ikke beregnes: "+type(exc).__name__)
        w=st.session_state.get(keybase+"walk_result")
        pinned=(since,anchor,int(structure_tf),float(nominal),float(fee),float(spread))
        if w is not None and st.session_state.get(keybase+"walk_dataset")!=pinned:
            st.info("Markedsdata, kostnader eller periode er endret. Kjør walk-forward på nytt.")
        elif w is not None:
            st.caption(f"Train {w.start_utc} → {w.split_utc} ({w.train_bars} 1m-barer) · "
                       f"Holdout → {w.end_utc} ({w.test_bars} 1m-barer)")
            if w.status!="SCORED":
                st.warning("Ingen gyldig treningsvinner: "+w.status+
                           ". Ingen strategi bør anbefales fra denne splitt.")
            else:
                winner=next(c for c in w.candidates if c.selected_on_training)
                st.metric("Valgt fra treningsdata",winner.name)
                a1,a2,a3=st.columns(3)
                a1.metric("Holdout netto",f"{winner.holdout_net_pct:+.3f}%")
                a2.metric("Holdout maks DD",f"{winner.holdout_drawdown_pct:.3f}%")
                a3.metric("Holdout handler",winner.holdout_executions)
            if w.candidates:
                table=pd.DataFrame([{
                    "Valgt på train":"JA" if x.selected_on_training else "",
                    "Strategi":x.name,
                    "Train netto %":round(x.training_net_pct,3),
                    "Train DD %":round(x.training_drawdown_pct,3),
                    "Train ordreendringer":x.training_executions,
                    "Holdout netto %":round(x.holdout_net_pct,3),
                    "Holdout DD %":round(x.holdout_drawdown_pct,3),
                    "Holdout ordreendringer":x.holdout_executions,
                    "Holdout kostnad %":round(x.holdout_cost_pct,3),
                } for x in w.candidates])
                st.dataframe(table.sort_values("Train netto %",ascending=False),
                             hide_index=True,use_container_width=True)

    with st.expander("Revisjon: alle signaler, fills og tidsrammebytter"):
        st.caption("En flat-posisjon bekreftes her i SIM. Den er IKKE Saxo-verifisert.")
        st.dataframe(pd.DataFrame(focus.decisions,
                     columns=["Ferdig candle UTC","Årsak","Fra enheter","Til enheter","MACD-min"]),
                     hide_index=True,use_container_width=True)
        st.dataframe(pd.DataFrame(focus.fills,
                     columns=["Neste åpen UTC","Etter-fill enheter","Årsak","MACD-min","Fyllpris"]),
                     hide_index=True,use_container_width=True)
        st.dataframe(pd.DataFrame(focus.timeframe_changes,
                     columns=["Besluttet UTC","Fra min","Til min","Årsak"]),
                     hide_index=True,use_container_width=True)
    with st.expander("Regimer · bidrag til nettoresultat"):
        st.caption("Retning/effektivitet basert på tidligere 20 fullførte 1m closes. "
                   "Bidragene er additive prosentpoeng, ikke regimevis sammensatt avkastning.")
        st.dataframe(pd.DataFrame(_regime_contributions(focus,bars)),
                     hide_index=True,use_container_width=True)
    st.warning("AEn er et tilbakeblikk med forenklet neste-bar-fill, uten faktisk Saxo-slippage, "
               "finansiering, intrabar stops, marginvalidering eller framoverskuende PAPER-ledger. "
               "Ikke tolk lønnsomhet eller enhetsstørrelse som LIVE-klar.")
