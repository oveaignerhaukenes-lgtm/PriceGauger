"""03 Oslo session loss diagnostics: actual Saxo NAV vs PAPER alternatives.

All broker evidence and market OHLC are READ ONLY. The comparison runs pure
strategy_lab_v2_replay on strictly historical, canonical exact-UIC 1m candles.
No order, strategy config, exposure or LIVE authority is ever written.
"""
from __future__ import annotations

from dataclasses import asdict,replace
from datetime import datetime,date,timedelta,timezone
import json

import pandas as pd
import streamlit as st

from autotrader_saxo_account_truth_v1 import load_account_truth_v1
from autotrader_account_learning_v1 import load_account_learning_executions_v1
from autotrader_saxo_strategy_timeline_v1 import observed_live_nav_windows_v1
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from instrument_registry_v2 import list_subscribed_sources_v2
from strategy_lab_v2_replay import (
    ReplayCostsV2,replay_v3_strategy_v2,MAX_BARS,
)
from autotrader_v3_session_loss_lab_v1 import (
    OSLO,utc,current_oslo_session,oslo_session_start,
    account_session_result,summarize_fleet_sessions,
    funded_account_cohort_v1,MAX_PRE_RESET_BASELINE,
    split_completed_regimes,market_session_coverage,replay_session_delta,
    filter_reconciled_account_fills,load_exact_product_executions,
    fill_price_followthrough,proposal_from_evidence,
)

st.set_page_config(page_title="AutoTrader · Tapslab 03:00",layout="wide")
st.title("AutoTrader · Taps- og regimelab")
st.caption(
    "Saxo-døgn fra klokken 03:00 Europe/Oslo · alle kontoers "
    "verifiserte TotalValue · eide V3-handler · prisregimer · "
    "uavhengige mekaniske PAPER-scenarier."
)
st.warning(
    "Kun forskning. Endringer i Saxo kontoverdi er IKKE dokumentert "
    "handelsresultat før kontantstrømmer, funding, FX, kostnader og "
    "manuelle handler er avstemt. PAPER-vinner i samme periode er "
    "etterpåklokskap, ikke en dokumentert fremtidig fordel. "
    "Denne siden har ingen LIVE-handelsmyndighet."
)

clock=datetime.now(timezone.utc)
default_start=current_oslo_session(now=clock)
default_day=default_start.astimezone(OSLO).date()
day=st.date_input("Saxo-døgn (starter kl. 03:00 norsk tid)",
                  value=default_day,max_value=clock.astimezone(OSLO).date())
start=oslo_session_start(day)
finish=min(oslo_session_start(day+timedelta(days=1)),clock)
st.caption(
    f"Faktisk analysevindu: **{start.astimezone(OSLO):%d.%m %H:%M %Z}** "
    f"til **{finish.astimezone(OSLO):%d.%m %H:%M %Z}**. "
    "Nærmeste pålitelige kontomåling rundt kl. 03 brukes (inntil 2 minutter "
    "før eller 12 minutter etter). Verdien er tilnærmet, aldri interpolert."
)
if finish<=start:
    st.info("Dette handelsdøgnet har ennå ikke begynt.")
    st.stop()

try:
    source_list=tuple(x for x in list_subscribed_sources_v2(provider="saxo")
                      if str(x.provider_instrument_id).isdigit()
                      and ("tech" in x.market_name.lower()
                           or "nas" in x.market_name.lower()))
except Exception as exc:
    st.error("Saxo produktregister utilgjengelig: "+type(exc).__name__)
    source_list=()
source=st.selectbox(
    "Marked / eksakt UIC for historiske strategi-alternativer",
    source_list,format_func=lambda x:
    f"{x.market_name} · {x.display_name} · UIC {x.provider_instrument_id}"
) if source_list else None
if source is None:
    st.info("Ingen abonnement på Tech100-priser funnet. "
            "Saxo-kontoundersøkelsen kan likevel kjøres.")

st.subheader("Kostnadsscenario (PAPER, ikke arkiverte Saxo-kostnader)")
p1,p2,p3=st.columns(3)
per_point=p1.number_input("NOK per indekspoeng × lot (antakelse)",
                          min_value=.001,value=10.,step=1.)
spread=p2.number_input("Spread i basispunkter (antakelse)",
                       min_value=0.,value=3.,step=.5)
variable=p3.number_input("Variabel kostnad, bp per side",
                         min_value=0.,value=2.,step=.5)
c1,c2,c3=st.columns(3)
fixed=c1.number_input("Fast kostnad i NOK / ordre",min_value=0.,value=1.,step=.5)
max_lots=c2.number_input("Maksimal PAPER-posisjon, lot",min_value=.01,
                         value=.03,step=.01,format="%.2f")
nav=c3.number_input("PAPER-startkapital (NOK)",min_value=100.,
                    value=10000.,step=1000.)

if st.button("Analyser tapsdagen og test strategier",type="primary"):
    try:
        # Explicit bounded historical data. No Saxo GET calls for the analysis.
        snapshots=load_account_truth_v1(days=14)
        funded,zero_balance_accounts=funded_account_cohort_v1(
            samples=snapshots,end=finish)
        # Cohort comes from latest verified broker NAV, not only those
        # accounts that happen to possess a 03:00 baseline.
        groups={aid:[] for aid in funded}
        for sample in snapshots:
            at=utc(sample["observed_at"])
            aid=str(sample["account_id"])
            if start-MAX_PRE_RESET_BASELINE<=at<=finish and aid in groups:
                groups[aid].append(sample)
        account_results=tuple(
            replace(account_session_result(
                account_id=aid,samples=groups[aid],
                start=start,end=finish),account_name=name)
            for aid,name in sorted(funded.items(),key=lambda x:x[1])
        )
        account_rows=[]
        events_by_account={}
        contexts={}
        account_labels={}
        for result in account_results:
            samples=groups[result.account_id]
            account_labels[result.account_id]=result.account_name
            try:
                raw=(load_exact_product_executions(
                    account_id=result.account_id,
                    uic=int(source.provider_instrument_id),
                    asset_type=str(source.asset_type),
                    start=start,end=finish)
                    if source is not None else
                    load_account_learning_executions_v1(
                        account_id=result.account_id,since=start))
                fills=filter_reconciled_account_fills(
                    executions=raw,account_id=result.account_id,
                    start=start,end=finish)
            except Exception:
                fills=None
            events_by_account[result.account_id]=fills
            account_rows.append({
                "Konto":result.account_name,
                "Valuta":result.currency,
                "Starttid norsk":(
                    result.start_observed_at.astimezone(OSLO).strftime("%H:%M")
                    if result.start_observed_at else None),
                "Sluttid norsk":(
                    result.end_observed_at.astimezone(OSLO).strftime("%H:%M")
                    if result.end_observed_at else None),
                "Avvik fra 03 (min)":result.baseline_delay_minutes,
                "Siste måling alder (min)":result.latest_age_minutes,
                "Målinger":result.samples,
                "Start TotalValue":result.baseline_value,
                "Slutt TotalValue":result.latest_value,
                "Endring (uavstemt)":result.nav_change,
                "Endring % (uavstemt)":result.nav_change_pct,
                "Maks observert DD %":result.worst_observed_drawdown_pct,
                "Avstemte V3-ordre":len(fills) if fills is not None else None,
                "Datakvalitet":result.status,
            })
            try:
                from autotrader_saxo_strategy_timeline_v1 import (
                    strategy_periods_from_snapshots_v1,
                )
                contexts[result.account_id]=tuple(
                    p for p in strategy_periods_from_snapshots_v1(samples)
                    if p.live_armed)
            except Exception:
                contexts[result.account_id]=()
        fleet=summarize_fleet_sessions(account_results)
        market_rows=()
        regimes=()
        coverage=None
        paper=[]
        failures={}
        if source is not None:
            market_rows=CanonicalMarketBarStoreV2().load_instrument_range(
                instrument_id=int(source.instrument_id),
                start=start-timedelta(hours=10),end=finish,
                limit=MAX_BARS+1)
            if len(market_rows)>MAX_BARS:
                raise ValueError("For mye kanonisk markedshistorikk (over 3000 1m). "
                                 "Velg smalere døgn eller utvid trygg replaygrense.")
            clipped=tuple(x for x in market_rows
                          if start<=utc(x.bar_time)<finish)
            coverage=market_session_coverage(bars=clipped,start=start,end=finish)
            regimes=split_completed_regimes(
                clipped,minutes=30,start=start,end=finish)
            if coverage["comparable"] and len(market_rows)>=90:
                costs=ReplayCostsV2(
                    point_value_nok=float(per_point),
                    spread_bps=float(spread),variable_fee_bps=float(variable),
                    fixed_fee_nok=float(fixed),lot_step=.01,
                    max_lots=float(max_lots),
                    starting_nav_nok=float(nav),
                    source="USER_MANUAL_SCENARIO_NOT_SAXO_VERIFIED",
                )
                candidates=(
                    ("macd-stoch-v2-1","1m"),
                    ("macd-stoch-v2-1","2m"),
                    ("macd-stoch-v2-2-flip","1m"),
                    ("macd-stoch-rhythm-build","1m"),
                    ("macd-histogram","2m"),
                    ("macd-flip","2m"),
                    ("pricetrend-1","2m"),
                    ("sma-9-21-baseline","2m"),
                )
                for key,timeframe in candidates:
                    try:
                        replay=replay_v3_strategy_v2(
                            strategy_key=key,bars=market_rows,
                            costs=costs,timeframe=timeframe)
                        delta=replay_session_delta(replay,start=start,end=finish)
                        if delta is None:
                            failures[f"{key} {timeframe}"]="No PAPER NAV baseline near 03:00"
                            continue
                        paper.append(dict(delta,timeframe=timeframe,
                            drawdown_whole_replay_pct=replay.drawdown_pct,
                            total_whole_replay_cost_nok=replay.total_cost_nok,
                            source_uic=int(source.provider_instrument_id)))
                    except Exception as exc:
                        failures[f"{key} {timeframe}"]=str(exc)[:180]
        followthrough={}
        if market_rows and source is not None:
            for account_id,fills in events_by_account.items():
                followthrough[account_id]=fill_price_followthrough(
                    fills=fills,bars=market_rows,account_id=account_id)
        proposals=proposal_from_evidence(
            regimes=regimes,account_results=account_results,
            executions_available=any(v is not None for v in events_by_account.values()),
        )
        st.session_state["losslab:report"]={
            "key":(str(day),int(source.instrument_id) if source else None,
                   per_point,spread,variable,fixed,max_lots,nav),
            "session_start":start.isoformat(),"session_end":finish.isoformat(),
            "account_results":account_rows,"fleet":fleet,
            "zero_balance_accounts":zero_balance_accounts,
            "funded_source_count":len(funded),
            "report_generated_at":datetime.now(timezone.utc).isoformat(),
            "contexts":contexts,"fills":events_by_account,
            "account_labels":account_labels,
            "followthrough":followthrough,"regimes":regimes,"paper":paper,"errors":failures,
            "proposals":proposals,"source":source.market_name if source else None,
            "raw_bars":len(market_rows),
            "cashflows_reconciled":False,
            "market_session_coverage":coverage,
        }
    except Exception as exc:
        st.session_state.pop("losslab:report",None)
        st.error("Tapsanalysen feilet uten endringer i LIVE: "
                 +type(exc).__name__+": "+str(exc)[:240])

report=st.session_state.get("losslab:report")
if report:
    current_key=(str(day),int(source.instrument_id) if source else None,
                 per_point,spread,variable,fixed,max_lots,nav)
    if report["key"]!=current_key:
        st.info("Input er endret. Kjør analysen på nytt for dette vinduet.")
    else:
        st.divider()
        st.subheader("1 · Faktiske Saxo-snapshot siden 03:00")
        gathered=utc(report["report_generated_at"])
        minutes_old=(datetime.now(timezone.utc)-gathered).total_seconds()/60
        st.caption(
            f"**Rapport hentet:** {gathered.astimezone(OSLO):%d.%m %H:%M:%S} "
            f"norsk tid · {minutes_old:.1f} minutter gammel. "
            "Kontoverdi oppdateres IKKE automatisk mens rapporten er åpen. "
            "Trykk «Analyser tapsdagen og test strategier» på nytt for nye målinger."
        )
        if minutes_old>=5:
            st.warning("Rapporten er over fem minutter gammel. "
                       "Tallene kan ikke sammenlignes direkte med Saxo-appen nå.")
        fund_count=report["funded_source_count"]
        if not fund_count:
            st.error("Fant ingen finansierte Saxo-kontoer med ferske, "
                     "lagrede kontoverdier. Ikke tolk dette som null tap.")
        elif report["account_results"]:
            st.caption(
                f"{fund_count} finansierte kontoer identifisert fra "
                "historiske Saxo-observasjoner i siste 24 timer. "
                f"{len(report['zero_balance_accounts'])} nullkonti holdes utenfor."
            )
            for row in report["account_results"]:
                with st.container(border=True):
                    st.markdown(f"**{row['Konto']} · {row['Valuta']}**")
                    status=row["Datakvalitet"]
                    if status=="OBSERVED_NAV_UNADJUSTED":
                        st.metric("Observert kontoverdiendring (ikke dagsresultat)",
                                  f"{row['Endring % (uavstemt)']:+.2f} %",
                                  f"{row['Endring (uavstemt)']:+.2f} {row['Valuta']}",
                                  delta_color="normal")
                    else:
                        status_labels={
                            "NO_VERIFIED_NAV":"Ingen gyldige kontomålinger i vinduet",
                            "BASELINE_TOO_LATE":"Ingen pålitelig baseline innen 2 min før / 12 min etter 03:00",
                            "LATEST_TOO_OLD":"Siste kontomåling er for gammel",
                            "INSUFFICIENT_SAMPLES":"For få kontomålinger",
                        }
                        st.warning(status_labels.get(status,status)+
                                   " – ingen dagsendring kan rapporteres.")
                    st.caption(
                        f"Baseline nær 03: {row['Starttid norsk'] or 'mangler'} "
                        f"({row['Avvik fra 03 (min)']:+.1f} min fra 03:00)"
                        if row["Forsinkelse etter 03 (min)"] is not None
                        else "Startmåling: mangler"
                    )
                    st.caption(
                        f"Sluttmåling: {row['Sluttid norsk'] or 'mangler'} "
                        f"({row['Siste måling alder (min)']:.1f} min eldre enn analyse)"
                        if row["Siste måling alder (min)"] is not None
                        else "Sluttmåling: mangler"
                    )
                    st.caption(
                        f"{row['Målinger']} pålitelige målinger. "
                        f"Startverdi: {row['Start TotalValue'] if row['Start TotalValue'] is not None else 'ukjent'} "
                        f"· sluttverdi: {row['Slutt TotalValue'] if row['Slutt TotalValue'] is not None else 'ukjent'} "
                        f"{row['Valuta']}."
                    )
        else:
            st.error("Ingen lagrede kontomålinger i perioden. "
                     "Kan ikke rekonstruere dagens Saxo-resultater.")
        st.subheader("Kontroll av samlet datadekning")
        for subtotal in report["fleet"]:
            included=subtotal["accounts"]
            total=subtotal["expected_funded_accounts"]
            if subtotal["status"]=="OBSERVED_COHORT_APPROX":
                st.metric(
                    f"Observert NAV-endring {subtotal['currency']} "
                    f"({included}/{total} kontoer, tilnærmet)",
                    f"{subtotal['unadjusted_nav_pct']:+.2f} %",
                    f"{subtotal['unadjusted_nav_delta']:+.2f} {subtotal['currency']}"
                )
                st.caption("Tidsstempler er samordnet innen fem minutter. "
                           "Fortsatt ikke Saxos offisielle daglige avkastning.")
            else:
                st.error(
                    f"Ingen gyldig samlet dagsprosent i {subtotal['currency']}: "
                    f"{included}/{total} finansierte kontoer kvalifiserer. "
                    f"Årsak: {subtotal['status']}."
                )
                if subtotal["excluded_names"]:
                    st.caption("Utelatte kontoer: "+
                               ", ".join(subtotal["excluded_names"]))
                st.caption(
                    "En beregnet DELSUM er ikke dagens totalresultat. "
                    f"Kun disse kontoene hadde en endring på "
                    f"{subtotal['subtotal_change_only']:+.2f} "
                    f"{subtotal['currency']} i sine observerte vinduer."
                    if subtotal["subtotal_change_only"] is not None else
                    "Ingen kvalifisert delsum."
                )
        with st.expander("Kontomålinger – komplett råoversikt og tidspunkt"):
            if report["account_results"]:
                st.dataframe(pd.DataFrame(report["account_results"]),
                             hide_index=True,use_container_width=True)
            if report["fleet"]:
                st.dataframe(pd.DataFrame(report["fleet"]),
                             hide_index=True,use_container_width=True)
        st.caption(
            "Endring % = (siste verifiserte Saxo TotalValue / nærmeste "
            "verifiserte verdi rundt 03:00 − 1) × 100. "
            "Nærmeste baseline kan være inntil to minutter FØR 03:00. "
            "Vi har ikke nødvendigvis en måling ved nøyaktig 03:00, "
            "og beregner aldri et kunstig startpunkt eller manglende kontoer. "
            "Kontoendringene er ikke justert for innskudd, uttak, "
            "finansiering, valutakurser eller manuelle handler. "
            "Saxos daglige %-tall må derfor stå som en egen, uavhengig fasit."
        )
        st.subheader("2 · Faktiske V3-ordre og observert strategi")
        # Persist labels with the report: Streamlit reruns the full script
        # without repeating heavy Saxo/price queries on button-less refreshes.
        named=report["account_labels"]
        for aid,periods in report["contexts"].items():
            label=named.get(aid,"Konto …"+aid[-4:])
            with st.expander(f"{label} · avstemte V3-hendelser / strategi"):
                if periods:
                    st.dataframe(pd.DataFrame([{
                        "Strategi":p.strategy_key,"TF":p.timeframe,
                        "Først observert":p.first_observed.astimezone(OSLO),
                        "Sist observert":p.last_observed.astimezone(OSLO),
                        "Instans":p.instance_id[:8],
                    }for p in periods]),hide_index=True,use_container_width=True)
                else:st.caption("Ingen entydig LIVE-strategi på lagret Saxo-konto.")
                fills=report["fills"].get(aid)
                if fills is None:
                    st.warning("Ordreloggen utilgjengelig – ikke tolket som null handler.")
                elif fills:
                    st.dataframe(pd.DataFrame([{
                        "Tid norsk":utc(ev["executed_at"]).astimezone(OSLO),
                        "Instans":str(ev["instance_id"])[:8],
                        "Handling":ev["action"],"Side":ev["side"],
                        "Faktisk delta lot":ev["amount"],
                        "Før lot":ev["inventory_before"],
                        "Etter lot":ev["inventory_after"],
                    }for ev in fills]),hide_index=True,use_container_width=True)
                else:st.caption("Ingen avstemte V3-ordre registrert i dette vinduet.")
        st.subheader("3 · Markedsregime (historisk 30m)")
        st.caption(f"{report['raw_bars']} lagrede kanoniske 1m-barer inkludert "
                   "10 timer for oppvarming. Hver regimeetikett beskriver bare "
                   "en FERDIG historisk 30m-periode, ikke et sanntidssignal.")
        if report["market_session_coverage"]:
            cov=report["market_session_coverage"]
            st.caption(
                f"Datadekning i selve handelsdøgnet: "
                f"{cov['observed_1m']}/{cov['expected_1m']} "
                f"barminutter ({cov['coverage_pct']:.1f} %). "
                "PAPER-rangering krever minst 80 % dekning og kursobservasjoner "
                "både nær 03:00 og vindusslutt."
            )
            if not cov["comparable"]:
                st.warning("Mangelfull markedsdekning. Ingen rangering av "
                           "alternativstrategier før sammenlignbare data finnes.")
        if report["regimes"]:
            st.dataframe(pd.DataFrame([{
                "Fra, norsk":r.from_at.astimezone(OSLO).strftime("%H:%M"),
                "Til, norsk":r.to_at.astimezone(OSLO).strftime("%H:%M"),
                "Regime (etterpå)":r.regime,
                "Kursretning %":round(r.direction_pct,3),
                "Effektivitet 0–1":round(r.efficiency_ratio,3),
                "Svingpunkter":r.completed_turns,
                "Maks–min bp":round(r.range_bps,1),
                "Median sving bp":round(r.median_swing_bps,2)
                                    if r.median_swing_bps is not None else None,
            }for r in report["regimes"]]),use_container_width=True,hide_index=True)
        else:
            st.warning("Ingen fullstendige sammenhengende 30m-vinduer: "
                       "kan ikke klassifisere markedet på tilgjengelige data.")
        st.subheader("4 · Hva skjedde etter avstemte innganger?")
        st.caption("Fremtidig kursretning 1/3/5 min etter FØRSTE observerte "
                   "1m-åpning etter Saxos posisjonsbekreftelse. "
                   "Positivt betyr at prisen senere gikk i posisjonens retning. "
                   "Dette er verken Saxo-fyllpris eller P/L, og en uverifisert "
                   "ordre gir ingen kunstig verdi.")
        raw_follow=[dict(row,Konto=report["account_labels"].get(aid,aid))
                    for aid,rows in report["followthrough"].items()
                    if rows is not None for row in rows]
        if raw_follow:
            st.dataframe(pd.DataFrame([{
                "Konto":x["Konto"],"Handling":x["action"],
                "Saxo-tid":x["executed_at"].astimezone(OSLO),
                "Posisjon etter (lot)":x["signed_lots_after"],
                "+1m retning bp":x.get("signed_future_1m_bps"),
                "+3m retning bp":x.get("signed_future_3m_bps"),
                "+5m retning bp":x.get("signed_future_5m_bps"),
            }for x in raw_follow]),hide_index=True,use_container_width=True)
        else:
            st.caption("Ingen kvalifiserte, eksakt avstemte innganger + "
                       "sammenhengende etterfølgende kursdata i perioden.")
        st.subheader("5 · Hvilke strategier kunne gjort det bedre? PAPER")
        st.caption(
            "Samme instrument, prisarkiv og manuelle kostnadsscenario. "
            "Strategiene er simulert med faktiske historiske 1m-kurser; "
            "signal på lukket bar fylles tidligst på NESTE 1m-åpning. "
            "PAPER-modeller er varmet opp før 03 og kan ha en posisjon ved "
            "vinduets start. Ingen av dem er avstemte live-resultater."
        )
        if report["paper"]:
            ranked=sorted(report["paper"],
                          key=lambda x:x["paper_change_pct"],reverse=True)
            st.dataframe(pd.DataFrame([{
                "Strategi":x["strategy"],"TF":x["timeframe"],
                "PAPER siden 03 (%)":round(x["paper_change_pct"],3),
                "PAPER endring (scenario-NOK)":round(
                    x["paper_change_scenario_units"],2),
                "Posisjon ved baseline":x["start_position_lots"],
                "Historiske PAPER-ordrer i vindu":x["session_decision_events"],
                "Start / slutt":f"{x['first_at'].astimezone(OSLO):%H:%M}–"
                                 f"{x['last_at'].astimezone(OSLO):%H:%M}",
            }for x in ranked]),hide_index=True,use_container_width=True)
            best=ranked[0]
            st.info(
                f"Beste ETTERPÅ på dette vinduet: {best['strategy']} "
                f"{best['timeframe']} ({best['paper_change_pct']:+.2f} % "
                "i PAPER-scenario). Dette er IKKE out-of-sample verifisering "
                "og ikke grunnlag for automatisk LIVE-bytte."
            )
        else:st.warning("Ingen sammenlignbare PAPER-resultater – se datamangler.")
        if report["errors"]:
            with st.expander("Strategier uten kvalifisert replay"):
                st.json(report["errors"])
        st.subheader("6 · Eksperimenter som kan forklare tapene")
        for name,method in report["proposals"]:
            st.markdown(f"**{name}** — {method}")
        st.caption(
            "Før en strategi anbefales LIVE: test på andre dager/uker, "
            "bekreft Saxo spread/kommisjon, ta hensyn til ordre-/filllatens "
            "og korriger kontoverdier for kontantstrømmer."
        )
        export={
            "schema":"PG_V3_LOSS_FORENSICS_V1","asof_utc":clock.isoformat(),
            "start_utc":report["session_start"],"end_utc":report["session_end"],
            "account_nav":report["account_results"],
            "fleet_nav":report["fleet"],
            "confirmed_v3_executions":report["fills"],
            "post_confirmation_price_direction":report["followthrough"],
            "observed_live_strategies":{
                k:[asdict(p) for p in v] for k,v in report["contexts"].items()},
            "completed_market_regimes":[asdict(x) for x in report["regimes"]],
            "counterfactual_paper_scenarios":report["paper"],
            "paper_failures":report["errors"],
            "research_hypotheses":report["proposals"],
            "market":report["source"],"archived_1m_rows":report["raw_bars"],
            "market_session_coverage":report["market_session_coverage"],
            "cashflows_reconciled":False,
            "live_orders_changed":False,
        }
        st.download_button(
            "Eksporter tapslab-rapport (JSON)",
            json.dumps(export,ensure_ascii=False,default=str,allow_nan=False),
            file_name=f"pg_tapslab_{day.isoformat()}.json",
            mime="application/json",
        )
else:
    st.caption("Kjør tapsanalysen for å hente eksakte Saxo-målinger fra databasen.")
