"""Strategy Lab v2 — universal catalog, causal multi-replay, Saxo account analysis."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime,timedelta,timezone
import json
import hashlib

import pandas as pd
import streamlit as st

from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from instrument_registry_v2 import list_subscribed_sources_v2
from live_sim_tv_charts_v1 import render_lab_tv_series
from strategy_lab_v2_click_chart import render_lab_v2_click_chart,replay_cursor_from_chart_click_v2
from strategy_lab_v2_replay import (
    ReplayCostsV2,PURE_V3,MAX_BARS,utc,
    strategy_catalog_v2,replay_v3_strategy_v2,
)
from strategy_lab_v2_saxo_costs import (
    saxo_replay_costs_v2,saxobank_accounts_v2,verified_replay_costs_v2,
)
from strategy_lab_v2_ai import (
    LabAIError,build_lab_asof_evidence_v2,lab_ai_evidence_fingerprint_v2,
    ask_lab_ai_v2,
)
from strategy_lab_v2_accounts import render_account_performance_v2
from autotrader_v3_ai_live_presets_v1 import AI_LIVE_PRESETS_V3

st.set_page_config(page_title="Strategilab v2",layout="wide")
st.title("Strategilab v2")
st.caption(
    "Historisk replay fra samme V3-strategifunksjoner · SAXO GET-only "
    "kostnadsscenarier · isolert PAPER, aldri LIVE-ordrer."
)
st.info(
    "SIM er en hendelsesbasert modell, ikke Saxo-fillhistorikk. Ferdig candle "
    "T gir tidligst PAPER-fill ved T+1m åpning. Manglende 1m-data stopper "
    "strategien; nåværende spread/kurtasje er ikke dokumentert historisk pris."
)
tabs=st.tabs(("Historisk SIM / Strategier","Kontoprestasjon",
              "HyperChase · 10s PAPER"))
with tabs[0]:
    left,right=st.columns([3.3,1.35],gap="large")
    with left:
        st.subheader("1 · Strategier og familier")
        st.caption("Åpne én eller flere strategifamilier. Sammenlign flere "
                   "på samme marked, instrument og UTC-vindu. "
                   "Ikke-replayklare modeller er synlige, men kan ikke velges "
                   "som om de var ferdig implementert.")
        catalog=strategy_catalog_v2()
        ai_presets={x.selector_key:x for x in AI_LIVE_PRESETS_V3}
        catalog["AI-forvaltning / forskningsmodeller"]=tuple({
            "key":x.selector_key,"name":x.label,
            "description":"Historiske AI-inngrep er ikke replaybare uten arkivert "
                          "as-of modellrespons. Vis derfor kun grunnstrategiens "
                          "mekaniske replay og analyser med manuell AI-dialog.",
            "replay_ready":False,"ai_capable":True,"runtime_ready":True,
        }for x in AI_LIVE_PRESETS_V3)
        chosen=[]
        for family,options in catalog.items():
            usable=sum(x["replay_ready"] for x in options)
            with st.expander(f"{family} · {usable}/{len(options)} replay-klare",
                             expanded=(family in ("MACD basis",
                                                  "MACD histogram / regime",
                                                  "Pris / fraktal"))):
                blocks=st.columns(2)
                for i,item in enumerate(options):
                    with blocks[i%2]:
                        if item["replay_ready"]:
                            selected=st.checkbox(
                                item["name"],key="slab2:select:"+item["key"],
                                value=item["key"] in (
                                    "macd-flip","macd-histogram",
                                    "precross-price-1m-macd2m",
                                ),
                                help=item["description"],
                            )
                            if selected:chosen.append(item["key"])
                        else:
                            st.caption("Ikke replay-klar · "+item["name"])
                            if not item["runtime_ready"]:
                                st.caption("Kun katalog / uimplementert V3-beslutningsmotor")
                            elif item["ai_capable"]:
                                st.caption("Krever lagret AI-beslutning ved hvert historisk punkt")
                            else:
                                st.caption("Krever isolert tilstandsadapter; ingen fabrikkert simulering")
                        if item["ai_capable"]:
                            st.caption("AI-dialog tilgjengelig, men ingen historisk AI-autotrading.")
        if not chosen:
            st.warning("Velg minst én replay-klar strategi i en familie.")

        st.subheader("2 · Marked, produkt og råhistorikk")
        try:
            sources=list_subscribed_sources_v2(provider="saxo")
        except Exception as exc:
            sources=()
            st.warning("Saxo-produktregister ikke tilgjengelig: "+type(exc).__name__)
        if not sources:
            st.info("Ingen Saxo-instrumenter med aktiv, lagret 1m-historikk. "
                    "Bruk Produktbrowser til å undersøke og abonnere på et "
                    "instrument før det kan spilles av i laben.")
            source=None
        else:
            markets=sorted({x.market_name for x in sources})
            market=st.selectbox("Marked",markets,key="slab2:market")
            matching=[x for x in sources if x.market_name==market]
            source=st.selectbox(
                "Produkt / eksakt Saxo UIC",
                matching,
                format_func=lambda x:(f"{x.display_name} · {x.symbol or ''} "
                                      f"· UIC {x.provider_instrument_id} · {x.asset_type or '?'}"),
                key="slab2:source",
            )
        c1,c2,c3=st.columns(3)
        timeframe=c1.selectbox("Signalperiode",("1m","2m","5m","10m","15m","30m","1h"),
                                index=1,key="slab2:timeframe")
        hours=c2.selectbox("Historisk vindu",(2,4,8,12,24,36,48),index=4,
                           key="slab2:hours")
        end_at=c3.date_input("Sluttdato (UTC)",value=datetime.now(timezone.utc).date(),
                             key="slab2:date")
        st.caption("Kanoniske 1m-prisbarer for akkurat den valgte Saxo-UIC. "
                   "For lange perioder, velg smalere vindu for å holde "
                   "beregning og prisdatakvalitet håndterbar.")
        st.subheader("3 · Saxo-kostnader og PAPER-premisser")
        SAXO_COST_OPTION="Saxo-kalibrert (GET, indikativt nå)"
        MANUAL_COST_OPTION="Manuelt scenario (ikke Saxo-verifisert)"
        cost_mode=st.radio("Kostnadsgrunnlag",
                           (SAXO_COST_OPTION,MANUAL_COST_OPTION),
                           horizontal=True,key="slab2:costmode")
        saxo_mode=(cost_mode==SAXO_COST_OPTION)
        if saxo_mode:
            evidence=None
            try:
                from saxo_provider import configured_client
                client=configured_client()
                accounts=saxobank_accounts_v2(client) if client else ()
            except Exception as exc:
                accounts=()
                st.warning("Saxo GET-kontoer utilgjengelige: "+type(exc).__name__)
            account=(st.selectbox(
                "Saxo-konto for kalkyle",accounts,
                format_func=lambda x:f"…{x['account_id'][-4:]} · {x['currency']}",
                key="slab2:costaccount",
            ) if accounts else None)
            if st.button("Hent indikativ pris, spread, FX og kurtasje fra Saxo",
                         disabled=source is None or account is None,
                         key="slab2:costfetch"):
                try:
                    evidence=saxo_replay_costs_v2(
                        client,source=source,account=account)
                    st.session_state["slab2:costevidence"]=evidence
                    st.session_state["slab2:costidentity"]=(
                        int(source.instrument_id),str(account["account_id"]))
                except Exception as exc:
                    st.session_state.pop("slab2:costevidence",None)
                    st.warning("Saxo-kostnader utilgjengelige: "+type(exc).__name__)
            if source is not None and account is not None and (
                st.session_state.get("slab2:costidentity")==(
                    int(source.instrument_id),str(account["account_id"]))
            ):
                evidence=st.session_state.get("slab2:costevidence")
            if evidence is not None:
                if evidence.status=="SAXO_COST_SCENARIO":
                    st.success("Saxo-kalibrert forskningsscenario klart. "
                               "Kostnader og valutakurser er indikative nå, ikke historiske.")
                else:
                    missing={
                        "Saxo-pris":evidence.price,
                        "Spread":evidence.spread_bps,
                        "NOK-verdi per prispoeng":evidence.point_value_nok,
                        "Kurtasje / eksplisitt kostnad":evidence.fixed_commission_nok,
                        "Minste førsteordre":evidence.minimum_trade_size,
                        "Lovlig ordreinkrement":evidence.increment_size,
                    }
                    st.warning("Saxo-kalibrert SIM mangler verifisering av: "+
                               ", ".join(k for k,v in missing.items() if v is None))
                    for note in evidence.notes:
                        st.caption("· "+str(note)[:200])
                    st.caption("Velg «Manuelt scenario» for å sammenligne "
                               "strategienes mekaniske signaler uten Saxo-kostnadsbevis.")
                with st.expander("Vis detaljert Saxo-kalkyle og kilde"):
                    st.json(asdict(evidence),expanded=True)
            else:
                st.caption("Hent dokumenterte Saxo-opplysninger før du simulerer "
                           "med Saxo-kalibrert kostnad.")
        else:
            a,b,c=st.columns(3)
            point_value=a.number_input("NOK per prispoeng per lot",
                        min_value=.001,value=10.,step=1.,key="slab2:point")
            spread=b.number_input("Spread (basispunkter), scenario",
                        min_value=0.,value=3.,step=.5,key="slab2:spread")
            percent=c.number_input("Variabel kostnad (basispunkter per side)",
                        min_value=0.,value=2.,step=.5,key="slab2:percent")
            a,b,c=st.columns(3)
            fixed=a.number_input("Fast kurtasje NOK per ordre",
                        min_value=0.,value=1.,step=.5,key="slab2:fixed")
            lot=b.number_input("Minste lot-inkrement",
                        min_value=.001,value=.01,step=.001,
                        format="%.3f",key="slab2:lot")
            max_lots=c.number_input("Maks lot per strategi",
                        min_value=.001,value=.03,step=.01,format="%.3f",
                        key="slab2:maxlot")
        starting_nav=st.number_input("Startverdi PAPER (NOK)",
                                    min_value=100.,value=10000.,step=1000.,
                                    key="slab2:nav")
        if saxo_mode:
            max_lots=st.number_input("Maks lot per strategi",min_value=.001,
                        value=.03,step=.01,format="%.3f",key="slab2:saxomaxlot")
        if st.button("Kjør historisk SIM for valgte strategier",
                     type="primary",disabled=source is None or not chosen,
                     key="slab2:run"):
            try:
                if saxo_mode:
                    if evidence is None:
                        raise ValueError("Hent Saxo-kostnader før replay")
                    costs=verified_replay_costs_v2(
                        evidence,max_lots=float(max_lots),
                        starting_nav_nok=float(starting_nav))
                else:
                    costs=ReplayCostsV2(
                        point_value_nok=float(point_value),
                        spread_bps=float(spread),variable_fee_bps=float(percent),
                        fixed_fee_nok=float(fixed),
                        lot_step=float(lot),max_lots=float(max_lots),
                        starting_nav_nok=float(starting_nav),
                        source="USER_MANUAL_SCENARIO_NOT_SAXO_VERIFIED",
                    )
                end=datetime.combine(end_at,datetime.max.time(),tzinfo=timezone.utc)
                start=end-timedelta(hours=int(hours))
                bars=CanonicalMarketBarStoreV2().load_instrument_range(
                    instrument_id=source.instrument_id,start=start,end=end,
                    limit=MAX_BARS+1)
                if len(bars)>MAX_BARS:
                    raise ValueError("Resultatet overskrider 3000 1m-barer; "
                                     "kort ned vinduet før replay.")
                if not bars:
                    raise ValueError("Ingen kanonisk Saxo 1m OHLC for valgt instrument/tid")
                st.session_state["slab2:lastbars"]=tuple(bars)
                successful={};issues={}
                for key in chosen[:12]:
                    try:
                        successful[key]=replay_v3_strategy_v2(
                            strategy_key=key,bars=bars,costs=costs,
                            timeframe="1m" if key in (
                                "precross-price-1m-macd2m",
                                "histogram-price-1m-macd2m",
                                "macd-stoch-rhythm-build",
                                "rhythm-trend-1",
                                "rhythm-build-fractal",
                                "rhythm-trend-fractal",
                            ) else timeframe,
                        )
                    except Exception as exc:
                        issues[key]=str(exc)[:170]
                st.session_state["slab2:results"]=successful
                st.session_state["slab2:issues"]=issues
                st.session_state["slab2:provenance"]={
                    "source_instrument_id":source.instrument_id,
                    "saxo_uic":source.provider_instrument_id,
                    "asset_type":source.asset_type,
                    "market":source.market_name,
                    "from":start.isoformat(),"to":end.isoformat(),
                    "signal_tf":timeframe,"costs":asdict(costs),
                    "selected_strategies":chosen[:12],
                }
            except Exception as exc:
                st.error("SIM ble ikke kjørt: "+str(exc)[:250])
        outcomes=st.session_state.get("slab2:results",{})
        problems=st.session_state.get("slab2:issues",{})
        if problems:
            with st.expander("Strategier som ikke kunne replayes"):
                st.json(problems)
        if len(chosen)>12:
            st.warning("Maks 12 strategier kjøres i én SIM-økt.")
        if outcomes:
            st.subheader("4 · Resultater, markører og tidsreise")
            info=st.session_state["slab2:provenance"]
            st.caption("Felles marked, prisvindue og kostnadsforutsetninger. "
                       "PAPER-resultat – ikke avstemte Saxo-ordrer.")
            labels={x["key"]:x["name"] for opts in catalog.values() for x in opts}
            rows=[{"Strategi":labels.get(key,key),
                   "Netto PAPER %":round(r.net_return_pct,3),
                   "Maks trekk %":round(r.drawdown_pct,3),
                   "Papirhandler":r.trades,
                   "Beregnede kostnader NOK":round(r.total_cost_nok,2),
                   "1m-datagap":r.skipped_gaps,"Kostnadskilde":r.cost_source}
                  for key,r in outcomes.items()]
            st.dataframe(pd.DataFrame(rows),hide_index=True,use_container_width=True)
            curves={}
            for name,result in outcomes.items():
                if result.points:
                    curves[labels.get(name,name)]=pd.Series(
                        [100*(p.nav_nok/float(info["costs"]["starting_nav_nok"])-1)
                         for p in result.points],
                        index=pd.DatetimeIndex([p.at for p in result.points]))
            if curves:
                curve=pd.concat(curves,axis=1).sort_index()
                render_lab_tv_series(curve,key="slab2:equity",
                                     title="Netto PAPER-kapital · alle valgte strategier (%)")

            primary=st.selectbox(
                "Strategi å spole i",list(outcomes),
                format_func=lambda key:labels.get(key,key),key="slab2:inspect")
            replay=outcomes[primary]
            n=len(replay.points)
            event_labels=[(e.at.isoformat()+" · "+e.kind+" · "+e.reason[:65],i)
                          for i,e in enumerate(replay.events)]
            if event_labels:
                jump=st.selectbox("Hopp til papirhandel",["—"]+[x[0] for x in event_labels],
                                  key="slab2:jump")
                if st.button("Vis valgt hendelse",key="slab2:jumpgo") and jump!="—":
                    event=replay.events[next(i for label,i in event_labels if label==jump)]
                    idx=next((i for i,p in enumerate(replay.points) if p.at>=event.at),n-1)
                    st.session_state["slab2:cursor"]=idx
                    st.rerun()
            pending_click=st.session_state.pop("slab2:pending_chart_cursor",None)
            if pending_click is not None:
                st.session_state["slab2:cursor"]=int(pending_click)
            cursor=st.slider("Spol: ferdig 1m-observasjon",min_value=0,
                             max_value=max(0,n-1),value=n-1,
                             key="slab2:cursor")
            focused=replay.points[cursor]
            st.caption(f"Valgt tidspunkt: {focused.at.isoformat()} UTC · "
                       f"papirposisjon {focused.lots:+g} lot · "
                       f"MACD-histogram {focused.macd_hist} · "
                       f"signal {focused.signal}.")
            historical=st.session_state["slab2:lastbars"]
            reveal_future=st.toggle(
                "Vis hele prisforløpet for å kunne klikke frem/tilbake",
                value=True,key="slab2:reveal_market",
                help="Når dette er PÅ, ser du fremtidige priser og PAPER-handler "
                     "i grafen. AI mottar fremdeles kun as-of-data ved spolepunktet. "
                     "Slå AV for en blind, fremoverrettet evaluering.")
            visible_bars=[b for b in historical if (
                reveal_future or utc(b.bar_time)<focused.at)]
            markers=[(e.at,e.after_lots-e.prior_lots,e.kind,1,e.price)
                     for e in replay.events if (
                         reveal_future or e.at<=focused.at)]
            clicked_time=render_lab_v2_click_chart(
                visible_bars,markers,key="slab2:tvchart",
                title=f"Pris + {labels.get(primary,primary)} · PAPER fills")
            if clicked_time is not None:
                event_key=(primary,int(clicked_time))
                if st.session_state.get("slab2:last_handled_chart_click")!=event_key:
                    st.session_state["slab2:last_handled_chart_click"]=event_key
                    clicked_index=replay_cursor_from_chart_click_v2(
                        points=replay.points,clicked_seconds=clicked_time)
                    if clicked_index is not None and clicked_index!=cursor:
                        st.session_state["slab2:pending_chart_cursor"]=clicked_index
                        st.rerun()
            with st.expander("Rådata og eksport · tidsstemplede datapunkter",
                             expanded=False):
                st.caption("Grafen avbilder kun historikk til valgt spolepunkt. "
                           "Nedlastingen omfatter HELE det valgte replay-vinduet, "
                           "med alle målinger/handelseventer slik at data kan "
                           "kontrolleres og lastes opp i ChatGPT for analyse.")
                package={
                    "schema":"PG_STRATEGY_LAB_V2_REPLAY_EXPORT",
                    "provenance":info,
                    "raw_saxo_1m_ohlc":[{
                        "time":utc(x.bar_time).isoformat(),
                        "open":x.open,"high":x.high,"low":x.low,
                        "close":x.close,"volume":x.volume,
                        "quality_flags":x.quality_flags,
                    }for x in historical],
                    "strategy_results":{
                        key:{"paper_points":[{
                                "time":p.at.isoformat(),"price":p.price,
                                "nav_nok":p.nav_nok,"lots":p.lots,
                                "macd_hist":p.macd_hist,"signal":p.signal,
                            }for p in res.points],
                            "paper_executions":[{
                                "at":e.at.isoformat(),"kind":e.kind,
                                "before":e.prior_lots,"after":e.after_lots,
                                "fill_price":e.price,"cost_nok":e.cost_nok,
                                "reason":e.reason,
                            }for e in res.events],
                        }for key,res in outcomes.items()},
                }
                raw=json.dumps(package,ensure_ascii=False,allow_nan=False)
                st.download_button("Eksporter komplett replay til ChatGPT (JSON)",
                                   data=raw,file_name="strategy_lab_v2_replay.json",
                                   mime="application/json",key="slab2:json")
                export=pd.DataFrame([{
                    "time_utc":p.at.isoformat(),"price":p.price,
                    "paper_nav_nok":p.nav_nok,"lots":p.lots,"signal":p.signal,
                    "macd_hist":p.macd_hist,
                }for p in replay.points])
                st.download_button("Eksporter valgt strategi (CSV)",
                                   data=export.to_csv(index=False),
                                   file_name="strategy_lab_v2_selected.csv",
                                   mime="text/csv",key="slab2:csv")
                st.json({"selected_asof":focused.at.isoformat(),
                         "last_5_observations":[{
                            "time":p.at.isoformat(),"price":p.price,"lots":p.lots,
                            "signal":p.signal,"paper_nav":p.nav_nok,
                         }for p in replay.points[max(0,cursor-4):cursor+1]]})
    with right:
        st.subheader("AI-dialog · as-of")
        st.caption(
            "Spol i simuleringen eller hopp til en handel. AI ser bare "
            "observasjoner tilgjengelige ved det valgte tidspunktet. "
            "AI-forslag er forskning; historisk AI-handling blir ikke "
            "oppdiktet, og LIVE-kontoer kan ikke styres herfra."
        )
        outcomes=st.session_state.get("slab2:results",{})
        if outcomes:
            selected_key=st.session_state.get("slab2:inspect")
            if selected_key not in outcomes:
                selected_key=next(iter(outcomes))
            replay=outcomes[selected_key]
            index=min(int(st.session_state.get("slab2:cursor",len(replay.points)-1)),
                      len(replay.points)-1)
            evidence=build_lab_asof_evidence_v2(
                strategy=selected_key,selected_at=replay.points[index].at,
                points=replay.points,events=replay.events,
                market=st.session_state["slab2:provenance"]["market"],
                product_key=str(st.session_state["slab2:provenance"]["saxo_uic"]),
                costs_source=replay.cost_source,
            )
            fingerprint=lab_ai_evidence_fingerprint_v2(evidence)
            if st.session_state.get("slab2:ai_fp")!=fingerprint:
                st.session_state["slab2:ai_fp"]=fingerprint
                st.session_state["slab2:ai_history"]=[]
            st.caption("Analysetid: "+evidence["as_of"])
            with st.expander("Eksakt AI-input (ingen fremtid)"):
                st.json(evidence)
            history=st.session_state.get("slab2:ai_history",[])
            for entry in history:
                st.markdown("**Du:** "+entry["question"])
                st.markdown("**AI:** "+entry["answer"])
            question=st.text_area(
                "Spør om signal, forsinkelse, falske brudd og forbedringer",
                value="Hva kunne gi et tidligere inngangssignal uten "
                      "uakseptabel whipsaw i dette vinduet?",
                key="slab2:ai_question",height=110,
            )
            if st.button("Analyser valgt tidspunkt med AI",
                         key="slab2:ai_send"):
                try:
                    answer=ask_lab_ai_v2(
                        evidence=evidence,question=question,history=history)
                    st.session_state["slab2:ai_history"]=history+[{
                        "question":question,"answer":answer}]
                    st.rerun()
                except LabAIError as exc:
                    st.warning("AI-analyse ikke fullført: "+str(exc))
                    st.caption("Diagnose: "+exc.code+" · Ingen PAPER- eller LIVE-ordre ble endret.")
                except Exception as exc:
                    st.warning("AI-analyse ikke fullført på grunn av en uventet feil. "
                               "Prøv igjen, eller eksporter replay-data til denne chatten.")
                    st.caption("Feilkategori: "+type(exc).__name__+
                               " · Ingen PAPER- eller LIVE-ordre ble endret.")
            st.caption("Eksportér JSON fra Rådata-panelet og last opp filen "
                       "i denne chatten for dypere analyse her.")
        else:
            st.info("Kjør minst én historisk SIM for å aktivere dialogen.")

with tabs[1]:
    render_account_performance_v2(
        sim_results=st.session_state.get("slab2:results",{}))


with tabs[2]:
    from strategy_lab_v2_hyper_chase_ui import render_hyper_chase_v1
    render_hyper_chase_v1()
