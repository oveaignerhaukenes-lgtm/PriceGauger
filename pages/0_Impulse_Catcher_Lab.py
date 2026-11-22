"""Same-model BBO PAPER replay and broker-reconciled V3 event observer."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from statistics import median

import pandas as pd
import streamlit as st

from autotrader_impulse_catcher_v1 import ImpulseCatcherConfig,ImpulseCatcherDecision
from autotrader_impulse_catcher_profiles_v1 import impulse_catcher_config
from autotrader_impulse_catcher_replay_v1 import (
    prepare_impulse_quotes,replay_impulse_catcher,summarize_impulse_replay,entry_regime_asof,
)
from autotrader_impulse_exit_regime_paper_v1 import (
    PAPER_EXIT_MODES, paper_exit_config_for_quote, r15_timeline_from_closed_1m_paper,
    STRUCTURE_EXIT_MODES, paper_structure_exit_config_for_quote,
)
from autotrader_price_structure_regime_paper_v1 import (
    price_structure_timeline_from_closed_1m_paper,
)
from autotrader_price_regime_timing_paper_v1 import (
    price_regime_timing_timeline_paper,
)
from autotrader_impulse_v14_chop_paper_v1 import ImpulseChopGatePaper
from autotrader_impulse_sideways_paper_v1 import (
    PAPER_MODES, SpecializedICEntryGatePaper,
    specialized_ic_config_paper, sideways_timeline_paper,
)
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from database import connect
from instrument_registry_v2 import resolve_instrument_source_v2


st.set_page_config(page_title="Impulse Catcher · Tech100",layout="wide")
st.title("Tech100 · Impulse Catcher")
st.caption("Forskning: LONG/FLAT og SHORT/FLAT, uavhengig av kontonavn og aktiv strategi")
st.info(
    "PAPER bruker identisk kausal signalmodell som LIVE, men antatt fyll på NESTE "
    "ekte Saxo bid/ask-observasjon. Kontrolldataene er ikke ekte gjennomførte "
    "handler. Reelle priser, kurtasje, kursglipp og Saxo-ordrehistorikk må "
    "avstemmes før simulert profitt kan sammenlignes med faktisk P/L."
)
st.caption("Identisk 3/10s inngang for v1.1, v1.2 og v1.3. Normal exit: 2s / 6s / "
           "6s + 3s støyjustert bekreftelse. Akutt reversering lukker i alle "
           "versjoner umiddelbart. Hypoteser, ikke dokumentert lønnsomhet.")
hours=st.selectbox("Samme kurshistorikk for begge strategier",(1,3,6,12),index=1)
max_rows=46000

if st.button("Kjør PAPER: v1.1 vs v1.2 vs v1.3",type="primary"):
    try:
        end=datetime.now(timezone.utc)
        start=end-timedelta(hours=hours)
        with connect() as db:
            raw=db.execute("""SELECT quote_at,received_at,bid,ask
                FROM lsim_hyper_quotes_1s WHERE provider_uic=4912
                AND quote_at>=? AND quote_at<=?
                ORDER BY quote_at LIMIT ?""",
                (start.isoformat(),end.isoformat(),max_rows+1)).fetchall()
        if len(raw)>max_rows:
            raise ValueError("Mer enn 46 000 observasjoner: velg et kortere tidsrom")
        quotes=prepare_impulse_quotes([dict(x) for x in raw])
        if len(quotes)<180:
            raise ValueError("For få ekte ferske BBO-observasjoner for en gyldig test")
        reports={(side,version):replay_impulse_catcher(
            quotes,impulse_catcher_config(side,version))
            for side in ("LONG","SHORT") for version in ("1.1","1.2","1.3")}
        st.session_state["impulse_catcher_replay"]={
            "stamp":end.isoformat(),"hours":hours,"quotes":len(quotes),
            "first":quotes[0].at.isoformat(),"last":quotes[-1].at.isoformat(),
            "reports":reports,"source_quotes":quotes,
        }
    except (ValueError,TypeError,OverflowError) as exc:
        st.warning(str(exc))
    except Exception as exc:
        st.error("PAPER-data kunne ikke leses: "+type(exc).__name__)

report=st.session_state.get("impulse_catcher_replay")
if report:
    if report["hours"]!=hours:
        st.warning("Observasjonsperioden er endret. Kjør ny test.")
    else:
        st.caption(f"Sist målt {report['stamp']}; {report['quotes']:,} godkjente BBO-prøver "
                   f"fra {report['first']} til {report['last']}.")
        cols=st.columns(2)
        for idx,side in enumerate(("LONG","SHORT")):
            r=report["reports"][(side,"1.1")]
            m=summarize_impulse_replay(r)
            with cols[idx]:
                st.subheader("LONG/FLAT · kontroll v1.1" if side=="LONG"
                             else "SHORT/FLAT · kontroll v1.1")
                c1,c2,c3=st.columns(3)
                c1.metric("PAPER-signaler",m["signals"])
                c2.metric("Lukkede PAPER-handler",m["completed"])
                c3.metric("Treffandel",f"{m['win_pct']:.1f}%" if m["win_pct"] is not None else "–")
                st.metric("Sum indekspoeng etter simulert bid/ask",
                          f"{m['net_index_points']:+.2f}")
                st.caption(f"Median per handel: {m['median_points']} poeng; "
                           f"entry-lag: {m['median_entry_delay_s']}s; "
                           f"exit-lag: {m['median_exit_delay_s']}s. "
                           f"Ufylt inngang/utgang: {m['unfilled_entries']}/"
                           f"{m['unfilled_exits']}; fortsatt åpen: {m['unfinished_positions']}.")
                if r.trades:
                    st.dataframe(pd.DataFrame([{
                        "Signal (UTC)":t.signal_at.isoformat(),
                        "PAPER entry":t.filled_at.isoformat(),
                        "PAPER exit":t.exited_at.isoformat(),
                        "P/L poeng":round(t.gross_points,2),
                        "MFE poeng":round(t.max_favorable_points,2),
                        "MAE poeng":round(t.max_adverse_points,2),
                        "Gevinst gitt tilbake":round(t.max_favorable_points-t.gross_points,2),
                    } for t in r.trades[-60:]]),hide_index=True,use_container_width=True)

        st.subheader("Exit-varianter · samme BBO-historikk")
        st.caption("Alle handler bruker neste ekte observerte bid/ask som antatt fill. "
                   "Urealiserte/ufylte handler krediteres aldri som gevinst. "
                   "Dette er ikke realisert kontogevinst.")
        comparisons=[]
        for side in ("LONG","SHORT"):
            for version in ("1.1","1.2","1.3"):
                result=report["reports"][(side,version)]
                m=summarize_impulse_replay(result)
                comparisons.append({
                    "Retning":side,"Variant":"v"+version,
                    "Signal":m["signals"],"Lukkede":m["completed"],
                    "Netto indekspoeng":m["net_index_points"],
                    "Treff %":m["win_pct"],"Median/handel":m["median_points"],
                    "Median hold sek":(round(median((t.exited_at-t.filled_at).total_seconds()
                                             for t in result.trades),1) if result.trades else None),
                    "Ufylt exit":m["unfilled_exits"],
                    "Åpne ved slutt":m["unfinished_positions"],
                })
        st.dataframe(pd.DataFrame(comparisons),hide_index=True,use_container_width=True)
        regime_rows=[]
        quote_times=tuple(q.at for q in report["source_quotes"])
        for side in ("LONG","SHORT"):
            for version in ("1.1","1.2","1.3"):
                r=report["reports"][(side,version)]
                for trade in r.trades:
                    regime_rows.append({
                        "Retning":side,"Variant":"v"+version,
                        "Tilstand ved signal":entry_regime_asof(
                            report["source_quotes"],trade.signal_at,quote_times=quote_times),
                        "PAPER-poeng":trade.gross_points,
                    })
        if regime_rows:
            st.subheader("På tvers av tilstander · klassifisert før handel")
            st.caption("Tilstand fra observerte foregående 60s: trend (effektivitet "
                       "≥0,55), sideveis (≤0,25), ellers blandet. Ufullstendige "
                       "vinduer merkes ukjent; ingen fremtidig pris brukes til etiketten.")
            state_df=pd.DataFrame(regime_rows)
            grouped=state_df.groupby(["Retning","Variant","Tilstand ved signal"],
                                     dropna=False)["PAPER-poeng"].agg(["count","sum","median"]).reset_index()
            grouped.columns=["Retning","Variant","Tilstand ved signal",
                             "Handler","Sum indekspoeng","Median/handel"]
            st.dataframe(grouped,hide_index=True,use_container_width=True)
        st.caption("Sammenlign både færre småtap og eventuell større tilbakegitt gevinst. "
                   "Utfallet kan snu i andre volatilitets- og trendregimer; "
                   "test på nye, kronologisk atskilte datoer før valg.")

        st.subheader("Daglig kalibrering · kun forslag")
        st.caption(
            "Velger nivåer på første 70 % av observerte quotes og vurderer de "
            "samme nivåene på siste 30 %. Dette er fremdeles en retrospektiv "
            "test, ikke bevis på morgendagens treff. LIVE-konfigurasjon endres aldri her."
        )
        if st.button("Sammenlign alternative impulsgrenser (7/9/12 poeng)"):
            quotes=report["source_quotes"]
            cutoff=max(150,int(0.7*len(quotes)))
            # Feed both segments a 150-quote warmup; only score fully
            # completed trades whose entry and exit are inside the segment.
            trials=[]
            for side in ("LONG","SHORT"):
                for threshold in (7.,9.,12.):
                    cfg=replace(ImpulseCatcherConfig(side=side),min_impulse_points=threshold)
                    train=replay_impulse_catcher(quotes[:cutoff],cfg)
                    holdout=replay_impulse_catcher(quotes[max(0,cutoff-150):],cfg)
                    valid=tuple(t for t in holdout.trades if
                                t.signal_at>=quotes[cutoff].at)
                    trials.append({
                        "Side":side,"Terskel":threshold,
                        "Kalibrering (handler)":len(train.trades),
                        "Kalibrering (poeng/handel)":round(train.net_points/len(train.trades),2)
                            if train.trades else None,
                        "Holdout (handler)":len(valid),
                        "Holdout (poeng/handel)":round(sum(t.gross_points for t in valid)/len(valid),2)
                            if valid else None,
                        "Foreløpig nok data":len(train.trades)>=30 and len(valid)>=10,
                    })
            st.session_state["impulse_catcher_trials"]=trials
        trials=st.session_state.get("impulse_catcher_trials")
        if trials:
            st.dataframe(pd.DataFrame(trials),hide_index=True,use_container_width=True)
            if any(t["Foreløpig nok data"] for t in trials):
                st.info("Minsteutvalget er nådd for noen varianter. Velg eventuell "
                        "ny versjon først etter kontroll mot en helt ny handelsdag.")
            else:
                st.warning("Ingen variant har foreløpig 30 fullførte handler i "
                           "kalibrering og 10 i holdout. Ingen optimaliseringsbeslutning.")

with st.expander("PAPER · Impulse exit etter fullført R15-MACD",expanded=False):
    st.caption(
        "Forhåndsdefinerte forsøk, samme virkelige 1s Saxo BBO og neste quote-fill: "
        "v1.3, +5s normal ventetid for begge, +5s bare SHORT i bearish R15, "
        "og +5s i medvind / −3s i motvind. Ingen endring i inngang, "
        "akutt reversering, quote-gap eller LIVE. R15 bruker bare 35 sammenhengende "
        "fullførte 15m-barer fra nøyaktig Saxo UIC 4912. "
        "Ukjent R15 gir uendret v1.3."
    )
    if report is None or report["hours"] != hours:
        st.info("Kjør først 1s BBO PAPER-replayet over, med valgt tidsrom.")
    elif st.button("Sammenlign exit: v1.3 / +5s / asymmetrisk R15",key="ic_r15_paper"):
        try:
            quotes=report["source_quotes"]
            source=resolve_instrument_source_v2(
                provider="saxo",provider_instrument_id="4912",require_subscription=True)
            history=CanonicalMarketBarStoreV2().load_instrument_range(
                instrument_id=int(source.instrument_id),
                start=quotes[0].at-timedelta(hours=48),
                end=quotes[-1].at,limit=4500)
            timeline=r15_timeline_from_closed_1m_paper(
                source_bars=history,cutoff=quotes[-1].at,
                market_name=source.market_name)
            if not timeline.closed_at:
                raise ValueError("Ingen gyldig R15-MACD: trenger minst 35 "
                                 "sammenhengende fullførte 15m-barer for samme UIC")
            outcomes={}
            for side in ("LONG","SHORT"):
                base=impulse_catcher_config(side,"1.3")
                for mode in PAPER_EXIT_MODES:
                    outcomes[(side,mode)]=replay_impulse_catcher(
                        quotes,base,
                        exit_config_asof=lambda at,side=side,mode=mode:
                            paper_exit_config_for_quote(
                                side=side,mode=mode,r15_state=timeline.state_asof(at)))
            st.session_state["impulse_r15_exit_paper"]={
                "stamp":report["stamp"],"hours":hours,"outcomes":outcomes,
                "timeline":timeline,"quotes":quotes,"bars":len(history),
                "holdout_at":quotes[int(len(quotes)*.7)].at,
            }
        except (ValueError,TypeError,OverflowError) as exc:
            st.warning(str(exc))
        except Exception as exc:
            st.error("R15-PAPER-test feilet: "+type(exc).__name__)
    paper=st.session_state.get("impulse_r15_exit_paper")
    if paper and report and paper["stamp"]==report["stamp"] and paper["hours"]==hours:
        unknown=sum(paper["timeline"].state_asof(q.at)=="UKJENT"
                    for q in paper["quotes"])
        st.caption(f"{paper['bars']} kanoniske 1m-barer; "
                   f"R15 UKJENT ved {unknown}/{len(paper['quotes'])} quotes. "
                   f"Kronologisk holdout begynner {paper['holdout_at'].isoformat()}.")
        comparison=[]
        for side in ("LONG","SHORT"):
            for mode in PAPER_EXIT_MODES:
                result=paper["outcomes"][(side,mode)]
                valid=tuple(t for t in result.trades if
                            t.filled_at>=paper["holdout_at"] and
                            t.exited_at<=paper["quotes"][-1].at)
                comparison.append({
                    "Side":side,"PAPER-exit":mode,"Handler":len(result.trades),
                    "Sum poeng":round(result.net_points,2),
                    "Treff %":round(result.win_fraction*100,1)
                         if result.win_fraction is not None else None,
                    "Median hold (s)":round(median(
                        (t.exited_at-t.filled_at).total_seconds()
                        for t in result.trades),1) if result.trades else None,
                    "Holdout handler":len(valid),
                    "Holdout poeng":round(sum(t.gross_points for t in valid),2),
                    "Holdout median":round(median(t.gross_points for t in valid),2)
                         if valid else None,
                    "Ufylt exit":result.unfilled_exits,
                    "Åpen slutt":result.unfinished_positions,
                })
        st.dataframe(pd.DataFrame(comparison),hide_index=True,use_container_width=True)
        st.warning("Variantene kan ta forskjellige senere innganger fordi exit endres. "
                   "En enkelt handelsdag/70–30-del er ikke en uavhengig "
                   "flerdags validering. Ingen LIVE-endring er autorisert.")

with st.expander("PAPER · Prisregime 30/60m med 6t bakgrunn",expanded=False):
    st.caption(
        "Impulser får fortsatt åpne LONG i BEAR og SHORT i BULL. "
        "Test både seks timers hovedstruktur og lokal vending etter sterk 30m "
        "prisbevegelse eller bekreftet 60m struktur. Bruker tidslikt gjennomsnitt "
        "av 1m (H+L+C)/3, trendens konsistens og prisbrudd – IKKE ekte VWAP. "
        "Seks timer er bakgrunn, ikke minstekrav for å oppdage vending. "
        "Normal exit kan justeres fra 6s til 3s mot / 11s med trenden. "
        "Ved ukjent regime brukes v1.3. Nødutgang og quote-gap er uendret. "
        "Ingen Saxo API-kall, LIVE-konto- eller ordreendringer."
    )
    if report is None or report["hours"] != hours:
        st.info("Kjør først 1s BBO PAPER-replayet over med samme tidsrom.")
    elif st.button("Sammenlign mottrend-exit mot prisstruktur",key="ic_structure_exit_paper"):
        try:
            quotes=report["source_quotes"]
            source=resolve_instrument_source_v2(
                provider="saxo",provider_instrument_id="4912",require_subscription=True)
            history=CanonicalMarketBarStoreV2().load_instrument_range(
                instrument_id=int(source.instrument_id),
                start=quotes[0].at-timedelta(hours=12),
                end=quotes[-1].at,limit=1500)
            timeline=price_structure_timeline_from_closed_1m_paper(
                source_bars=history,cutoff=quotes[-1].at,
                market_name=source.market_name)
            timing=price_regime_timing_timeline_paper(
                source_bars=history,cutoff=quotes[-1].at,
                market_name=source.market_name)
            if not timeline.closed_at:
                raise ValueError("Ingen fullførte 1m-priser for eksakt Saxo UIC 4912")
            outcomes={}
            for side in ("LONG","SHORT"):
                base=impulse_catcher_config(side,"1.3")
                for mode in (*STRUCTURE_EXIT_MODES,"adaptiv_30_60"):
                    outcomes[(side,mode)]=replay_impulse_catcher(
                        quotes,base,
                        exit_config_asof=lambda at,side=side,mode=mode:
                            paper_structure_exit_config_for_quote(
                                side=side,
                                mode=("struktur_medvind_venter_motvind_rask"
                                      if mode=="adaptiv_30_60" else mode),
                                structure_state=(timing.state_asof(at).effective_for_impulse_exit
                                      if mode=="adaptiv_30_60" else timeline.state_asof(at))))
            st.session_state["impulse_structure_exit_paper"]={
                "stamp":report["stamp"],"hours":hours,"outcomes":outcomes,
                "timeline":timeline,"timing":timing,"quotes":quotes,"bars":len(history),
                "holdout_at":quotes[int(len(quotes)*.7)].at,
            }
        except (ValueError,TypeError,OverflowError) as exc:
            st.warning(str(exc))
        except Exception as exc:
            st.error("Prisstruktur-PAPER-test feilet: "+type(exc).__name__)
    paper=st.session_state.get("impulse_structure_exit_paper")
    if paper and report and paper["stamp"]==report["stamp"] and paper["hours"]==hours:
        coverage={state:sum(paper["timeline"].state_asof(q.at)==state
                            for q in paper["quotes"])
                  for state in ("BEAR","BULL","UKJENT")}
        st.caption(f"{paper['bars']} lagrede fullførte 1m-priser; "
                   f"regime pr. quote: BEAR {coverage['BEAR']}, "
                   f"BULL {coverage['BULL']}, UKJENT {coverage['UKJENT']}. "
                   f"Holdout fra {paper['holdout_at'].isoformat()} UTC.")
        timing=paper["timing"]
        local_counts={state:sum(timing.state_asof(q.at).local==state
                                for q in paper["quotes"])
                      for state in ("BULL_30","BULL_60","BEAR_30","BEAR_60")}
        allowed_long=sum(timing.state_asof(q.at).regime_long_allowed
                         for q in paper["quotes"])
        st.caption("30/60m vendingsetiketter pr. quote: "+", ".join(
            f"{state}: {count}" for state,count in local_counts.items())+
            f". PAPER regime-LONG inngang tillatt ved {allowed_long}/"
            f"{len(paper['quotes'])} quotes (også UKJENT). "
            "Dette er **ikke** eksekverte eller faktisk filtrerte V3-handler.")
        comparison=[]
        for side in ("LONG","SHORT"):
            for mode in (*STRUCTURE_EXIT_MODES,"adaptiv_30_60"):
                result=paper["outcomes"][(side,mode)]
                valid=tuple(t for t in result.trades if
                            t.filled_at>=paper["holdout_at"] and
                            t.exited_at<=paper["quotes"][-1].at)
                comparison.append({
                    "Side":side,"PAPER-exit":mode,"Handler":len(result.trades),
                    "Sum poeng":round(result.net_points,2),
                    "Treff %":round(result.win_fraction*100,1)
                         if result.win_fraction is not None else None,
                    "Median hold (s)":round(median(
                        (t.exited_at-t.filled_at).total_seconds()
                        for t in result.trades),1) if result.trades else None,
                    "Holdout handler":len(valid),
                    "Holdout poeng":round(sum(t.gross_points for t in valid),2),
                    "Ufylt exit":result.unfilled_exits,
                    "Åpen slutt":result.unfinished_positions,
                })
        st.dataframe(pd.DataFrame(comparison),hide_index=True,use_container_width=True)
        st.warning("30/60m-tersklene er forhåndsdefinerte PAPER-hypoteser, ikke "
                   "verifisert på flere uavhengige handelsdager. "
                   "Ukjent regime betyr uendret exit. "
                   "Ingen kontoer, ordre eller aktive strategier endres.")

with st.expander("PAPER · Impulse Catcher v1.4 – blokkér åpenbare rangefeller",expanded=False):
    st.caption(
        "V1.4 er FORELØPIG BARE EN KANDIDAT. Samme 3/10s impulsinnganger, "
        "men et nytt veto ved minst fire betydelige 60s-reverseringer, "
        "retnings-effektivitet ≤0,20, bredt sideveis intervall og impuls "
        "som forblir inne i intervallet. En ekte utbruddsimpuls, "
        "manglende data og tvilstilfeller passerer. Ingen regimebasert "
        "blanket-blokkering av LONG eller SHORT. Samme fill/quote-gap/nødexit "
        "som v1.3. Sammenlign også med adaptive 30/60m utganger."
    )
    if report is None or report["hours"]!=hours:
        st.info("Kjør først 1s BBO PAPER-replayet over med ønsket periode.")
    elif st.button("Kjør v1.4 PAPER: filter / exit / kombinert",key="ic_v14_paper"):
        try:
            quotes=report["source_quotes"]
            source=resolve_instrument_source_v2(
                provider="saxo",provider_instrument_id="4912",require_subscription=True)
            history=CanonicalMarketBarStoreV2().load_instrument_range(
                instrument_id=int(source.instrument_id),
                start=quotes[0].at-timedelta(hours=12),
                end=quotes[-1].at,limit=1500)
            timing=price_regime_timing_timeline_paper(
                source_bars=history,cutoff=quotes[-1].at,
                market_name=source.market_name)
            outcomes={}
            baseline_vetoed={}
            for side in ("LONG","SHORT"):
                cfg=impulse_catcher_config(side,"1.3")
                gate=ImpulseChopGatePaper(quotes,cfg)
                outcomes[(side,"v1.3")]=replay_impulse_catcher(quotes,cfg)
                for mode,uses_gate,uses_exit in (
                    ("v1.4_filter",True,False),
                    ("adaptiv_exit",False,True),
                    ("v1.4_filter_pluss_exit",True,True),
                ):
                    outcomes[(side,mode)]=replay_impulse_catcher(
                        quotes,cfg,
                        entry_allowed_asof=(
                            (lambda decision,gate=gate: gate.evaluate(decision).allowed)
                            if uses_gate else None),
                        exit_config_asof=(
                            (lambda at,side=side:
                                paper_structure_exit_config_for_quote(
                                    side=side,mode="struktur_medvind_venter_motvind_rask",
                                    structure_state=timing.state_asof(at).effective_for_impulse_exit))
                            if uses_exit else None),
                    )
                removed=[]
                for trade in outcomes[(side,"v1.3")].trades:
                    original=ImpulseCatcherDecision(
                        side,"QUALIFIED_IMPULSE",trade.entry_signal_mid,
                        trade.signal_at,trade.entry_trigger_points,0.,
                        trade.entry_window_seconds)
                    if not gate.evaluate(original).allowed:
                        removed.append(trade)
                baseline_vetoed[side]={
                    "baseline_handler":len(removed),
                    "taps_handler":sum(t.gross_points<0 for t in removed),
                    "vinner_handler":sum(t.gross_points>0 for t in removed),
                    "sum_poeng":round(sum(t.gross_points for t in removed),2),
                }
            st.session_state["impulse_v14_paper"]={
                "stamp":report["stamp"],"hours":hours,
                "outcomes":outcomes,"baseline_vetoed":baseline_vetoed,
                "bars":len(history),"quotes":quotes,
                "holdout_at":quotes[int(.7*len(quotes))].at,
            }
        except (ValueError,TypeError,OverflowError) as exc:
            st.warning(str(exc))
        except Exception as exc:
            st.error("V1.4 PAPER feilet: "+type(exc).__name__)
    paper=st.session_state.get("impulse_v14_paper")
    if paper and report and paper["stamp"]==report["stamp"] and paper["hours"]==hours:
        st.caption(f"{len(paper['quotes'])} BBO-observasjoner, "
                   f"{paper['bars']} fullførte UIC-1m-barer. "
                   f"Siste 30%: {paper['holdout_at'].isoformat()} UTC og senere.")
        if paper["bars"]<61:
            st.warning("For lite sammenhengende 1m-prishistorikk for pålitelig "
                       "30/60m utgang: adaptive exit-varianter vil i praksis "
                       "bruke v1.3 der markedsregimet er UKJENT.")
        rows=[]
        for side in ("LONG","SHORT"):
            for mode in ("v1.3","v1.4_filter","adaptiv_exit",
                         "v1.4_filter_pluss_exit"):
                outcome=paper["outcomes"][(side,mode)]
                valid=tuple(t for t in outcome.trades if
                            t.filled_at>=paper["holdout_at"] and
                            t.exited_at<=paper["quotes"][-1].at)
                rows.append({
                    "Retning":side,"PAPER variant":mode,
                    "Kvalifiserte signal":outcome.signals,
                    "Veto":outcome.blocked_entries,
                    "Lukkede handler":len(outcome.trades),
                    "Sum indekspoeng":round(outcome.net_points,2),
                    "Treff %":round(100*outcome.win_fraction,1)
                        if outcome.win_fraction is not None else None,
                    "Holdout handler":len(valid),
                    "Holdout poeng":round(sum(t.gross_points for t in valid),2),
                    "Ufylt exit":outcome.unfilled_exits,
                    "Åpen slutt":outcome.unfinished_positions,
                })
        st.dataframe(pd.DataFrame(rows),hide_index=True,use_container_width=True)
        st.caption("Av de fullførte v1.3-baseline-handlene ville v1.4-vetoet "
                   "fjernet følgende isolerte signaler. Dette er IKKE lik "
                   "samlet strategigevinst: etterfølgende handler endres.")
        st.dataframe(pd.DataFrame([
            {"Retning":side,**stats}
            for side,stats in paper["baseline_vetoed"].items()
        ]),hide_index=True,use_container_width=True)
        st.warning("Ingen automatisk v1.4-strateginøkkel er registrert for LIVE. "
                   "Enkeltperioder og ikke-uavhengige signaler beviser ikke "
                   "fremtidig avkastning. Ta først nye dager i uavhengig holdout.")

with st.expander("PAPER · Sideveis Impulse Catcher og sjeldne motimpulser",expanded=False):
    st.caption(
        "Ny arbeidsdeling: regime-strategiene håndterer bekreftet opp-/nedtrend. "
        "IC får høyere impuls- og effektivitetskrav, 25s kjølepause og senere "
        "normal exit. Kun fullførte sammenhengende 1m-barer kan bekrefte "
        "SIDEWAYS; 30/60m retningskonflikt blir TRANSITION og handler ikke. "
        "Sjeldent sjokk-alternativ tillater kun ekstraordinære mottrendbrudd "
        "med 3s akselerasjon – ikke ordinære medtrend-innganger."
    )
    if report is None or report["hours"] != hours:
        st.info("Kjør først 1s BBO PAPER-replayet over med ønsket tidsrom.")
    elif st.button("Kjør PAPER: IC sideveis / sideveis + sjokk",key="ic_sideways_paper"):
        try:
            quotes = report["source_quotes"]
            source = resolve_instrument_source_v2(
                provider="saxo",provider_instrument_id="4912",require_subscription=True)
            history = CanonicalMarketBarStoreV2().load_instrument_range(
                instrument_id=int(source.instrument_id),
                start=quotes[0].at-timedelta(hours=3),
                end=quotes[-1].at,limit=1000)
            timeline = sideways_timeline_paper(
                source_bars=history,cutoff=quotes[-1].at,
                market_name=source.market_name)
            results={}
            for side in ("LONG","SHORT"):
                baseline = impulse_catcher_config(side,"1.3")
                results[(side,"v1.3")]=replay_impulse_catcher(quotes,baseline)
                cfg = specialized_ic_config_paper(side)
                for mode in PAPER_MODES:
                    gate = SpecializedICEntryGatePaper(
                        quotes=quotes, config=cfg,timeline=timeline,mode=mode)
                    results[(side,mode)] = replay_impulse_catcher(
                        quotes,cfg,entry_allowed_asof=lambda decision,gate=gate:
                        gate.evaluate(decision).allowed)
            st.session_state["ic_sideways_results"]={
                "stamp":report["stamp"],"hours":hours,
                "results":results,"bars":len(history),
                "quotes":quotes,"timeline":timeline,
                "holdout_at":quotes[int(.7*len(quotes))].at,
            }
        except (ValueError,TypeError,OverflowError) as exc:
            st.warning(str(exc))
        except Exception as exc:
            st.error("IC sideveis PAPER feilet: "+type(exc).__name__)
    sideways_paper=st.session_state.get("ic_sideways_results")
    if (sideways_paper and report and sideways_paper["stamp"]==report["stamp"]
        and sideways_paper["hours"]==hours):
        results=sideways_paper["results"]
        quotes=sideways_paper["quotes"]
        holdout_at=sideways_paper["holdout_at"]
        states=[sideways_paper["timeline"].state_asof(q.at).state
                for q in quotes[::60]]
        st.caption(
            f"{len(quotes)} reelle Saxo BBO, {sideways_paper['bars']} "
            f"fullførte 1m-barer, markedsprøver {len(states)}: "
            +", ".join(f"{s}={states.count(s)}" for s in sorted(set(states)))
            +f". Holdout starter {holdout_at.isoformat()}."
        )
        if not any(s=="SIDEWAYS_CONFIRMED" for s in states):
            st.warning("Ingen bekreftet sideveis periode i disse markedsprøvene. "
                       "At en spesialisert modell avviser alt, er ikke bevis for "
                       "lønnsomhet; velg flere sammenhengende siderange-perioder.")
        rows=[]
        for side in ("LONG","SHORT"):
            for mode in ("v1.3",)+PAPER_MODES:
                result=results[(side,mode)]
                valid=tuple(t for t in result.trades
                            if t.filled_at>=holdout_at and t.exited_at<=quotes[-1].at)
                brief=sum((t.exited_at-t.filled_at).total_seconds()<20
                          for t in result.trades)
                rows.append({
                    "Retning":side,"Variant":mode,
                    "Signal":result.signals,"Veto":result.blocked_entries,
                    "Lukkede":len(result.trades),"<20s hold":brief,
                    "Poeng etter spread":round(result.net_points,2),
                    "Holdout handler":len(valid),
                    "Holdout poeng":round(sum(t.gross_points for t in valid),2),
                    "Ufylt exit":result.unfilled_exits,
                    "Åpen slutt":result.unfinished_positions,
                })
        st.dataframe(pd.DataFrame(rows),hide_index=True,use_container_width=True)
        st.warning(
            "Kun PAPER: spread via neste reelle bid/ask, men ingen Saxo-latens, "
            "faktiske fills eller konto-P/L. Ukjent regime blokkeres kun i disse "
            "to simulerte IC-variantene; ingen LIVE-innstillinger endres."
        )

st.subheader("LIVE-observasjoner · signal vs. Saxo-rekonsiliering")
try:
    with connect() as db:
        instances=db.execute("""SELECT i.instance_id,i.account_id,i.uic,i.asset_type,
            c.strategy_key,c.modifiers_json FROM autotrader_v3_engine_instances i
            JOIN autotrader_v3_config c ON c.trader_id=i.instance_id
            WHERE i.enabled=TRUE AND c.strategy_key IN (?,?,?,?,?,?,?,?)""",
            ("impulse-catcher-long-v1","impulse-catcher-short-v1",
             "impulse-catcher-long-v1-1","impulse-catcher-short-v1-1",
             "impulse-catcher-long-v1-2","impulse-catcher-short-v1-2",
             "impulse-catcher-long-v1-3","impulse-catcher-short-v1-3")).fetchall()
        try:
            since=(datetime.now(timezone.utc)-timedelta(days=7)).isoformat()
            logs=db.execute("""SELECT trader_id,strategy_key,quote_at,direction,
                action,trigger_points,baseline_points,window_seconds
                FROM pg_v3_impulse_signal_events
                WHERE quote_at>=? ORDER BY quote_at DESC LIMIT 250""",
                (since,)).fetchall()
            full_count=int(db.execute("""SELECT COUNT(*) AS n
                FROM pg_v3_impulse_signal_events WHERE quote_at>=?""",
                (since,)).fetchone()["n"])
            daily=db.execute("""SELECT SUBSTR(quote_at,1,10) AS utc_day,
                direction,action,COUNT(*) AS n FROM pg_v3_impulse_signal_events
                WHERE quote_at>=? GROUP BY SUBSTR(quote_at,1,10),direction,action
                ORDER BY utc_day,direction,action""",(since,)).fetchall()
        except Exception:
            logs=[]
            daily=[]
            full_count=0
        executions=[]
        for inst in instances:
            try:
                rows=db.execute("""SELECT executed_at,action,side,amount
                    FROM autotrader_v3_execution_events
                    WHERE instance_id=? AND account_id=? AND uic=? AND asset_type=?
                      AND executed_at>=?
                    ORDER BY executed_at DESC LIMIT 100""",(
                    inst["instance_id"],inst["account_id"],inst["uic"],inst["asset_type"],
                    datetime.now(timezone.utc)-timedelta(days=7))).fetchall()
                executions.extend(dict(r)|{"instance":str(inst["instance_id"])[:8]} for r in rows)
            except Exception:
                pass
    col1,col2,col3=st.columns(3)
    col1.metric("Registrerte impulsinstanser",len(instances))
    col2.metric("LIVE-modellsignaler (7d)",full_count)
    col3.metric("Saxo-rekonsilierte V3-hendelser (7d)",len(executions))
    if logs:
        st.caption("Modellsignal betyr IKKE ordrefyll. UIC, konto-eierskap, "
                   "posisjon, margin og låser avgjør om V3 utfører.")
        st.dataframe(pd.DataFrame([dict(row)|{"trader_id":str(row["trader_id"])[:8]}
                                   for row in logs]),hide_index=True,use_container_width=True)
        st.dataframe(pd.DataFrame(executions),hide_index=True,use_container_width=True)
        st.caption("Daglig frekvens (deterministisk observasjon, ingen automatisk tilpasning)")
        st.dataframe(pd.DataFrame([{"Dag (UTC)":x["utc_day"],
                                   "Retning":x["direction"],"Handling":x["action"],
                                   "Antall":x["n"]} for x in daily]),
                     hide_index=True,use_container_width=True)
    elif instances:
        st.caption("Impulsinstanser finnes, men ingen signaler er logget i siste 7 dager.")
    else:
        st.caption("Ingen nye impulsinstanser er registrert. Dette panelet armer "
                   "ikke kontoer og endrer ikke eksisterende Tech100-E.")
except Exception as exc:
    st.caption("LIVE-logg utilgjengelig inntil instanser/tabell er etablert: "
               +type(exc).__name__)
