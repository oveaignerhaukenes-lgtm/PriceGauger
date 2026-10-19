"""Saxo account-truth overview: live cash/equity history and temporal context.

Displays broker values, never synthetic strategy P/L. All views read the
immutable Saxo account snapshot ledger and the canonical execution log.
"""
from __future__ import annotations

import json
import pandas as pd
import streamlit as st

from autotrader_saxo_account_truth_v1 import (
    load_account_truth_v1,account_value_summary_v1,
    collect_saxo_account_truth_once_v1,
)
from autotrader_saxo_official_performance_v1 import (
    load_official_performance_v1,collect_official_performance_once_v1,
)
from autotrader_saxo_strategy_timeline_v1 import (
    build_saxo_account_strategy_chart_v1,observed_live_nav_windows_v1,
)
from autotrader_v3_instance_registry_v1 import load_v3_instances_v1
from database import connect


st.title("Kontostatistikk · Saxo fasit")
st.caption(
    "Kontoverdi fra Saxo, lagret automatisk omtrent hvert femte minutt, "
    "med hvilken strategi og hvilket marked som var aktivt ved målingen. "
    "Dette er ikke beregnet strategiavkastning."
)
with st.expander("Datakvalitet og definisjoner",expanded=False):
    st.markdown(
        "**Saxo TotalValue:** kontoverdi inklusive åpne posisjoner, "
        "ikke-bokførte transaksjoner og Saxos verdsettelsesregler. "
        "**Endring i TotalValue er ikke automatisk profitt**: innskudd, uttak, "
        "kontooverføringer, FX, finansiering og bokføringsforsinkelser "
        "må avstemmes først. Én konto kan også inneholde manuelle handler "
        "eller andre instrumenter. Strateginavn er en tidskobling, "
        "ikke dokumentert årsaksforklaring. "
        "Vi viser bare målinger med CalculationReliability=Ok i avkastningskurven. "
        "Ingen resultatstatistikk blir oppkonstruert for perioder før innsamlingen startet."
    )

if st.button("Hent Saxo-kontoverdi nå (kun GET)",key="account-truth-refresh"):
    with st.spinner("Leser Saxo-balansene uten å sende ordre..."):
        try:
            result=collect_saxo_account_truth_once_v1()
        except Exception as exc:
            st.error("Saxo-kontroll feilet: "+type(exc).__name__)
        else:
            st.info(
                f"Status: {result['status']} · lest: {result['seen']} · "
                f"lagret: {result['saved']} · mislykket: {result['failed']}. "
                f"Feilkoder: {result.get('errors',{})}. "
                "Høyst ett øyeblikksbilde per femminuttersvindu."
            )

days=st.selectbox("Periode",options=[1,7,14,30,90],index=1,
                  format_func=lambda x:f"{x} døgn",key="account-truth-days")
try:
    samples=load_account_truth_v1(days=days)
except Exception as exc:
    st.error("Kontoregnskapet kan ikke leses: "+type(exc).__name__)
    st.stop()

if not samples:
    st.info("Ingen Saxo-kontomålinger lagret ennå. Innsamling starter med neste worker-syklus; prøv «Hent Saxo-kontoverdi nå».")
    st.stop()

if len(samples)>=50000:
    st.warning(
        "Samlet kontooversikt viser bare de 50 000 nyeste målingene i valgt periode. "
        "Individuelle kontografer og observerte strategiperioder henter derimot "
        "hele den valgte perioden per konto. Ingen eldre målinger er slettet."
    )

frame=pd.DataFrame(samples)
frame["observed_at"]=pd.to_datetime(frame["observed_at"],utc=True)
frame["verified"]=frame["calculation_reliability"].str.lower().eq("ok")
accounts=frame.groupby(["account_id","account_name","currency"],sort=False)
overview=[]
for (aid,name,currency),data in accounts:
    clean=data[data["verified"]].sort_values("observed_at")
    if clean.empty:
        overview.append({"Konto":name,"Valuta":currency,"Siste verdi":None,
            "Endring i kontoverdi":None,"Målinger":0,
            "Kvalitet":"Ingen verifiserte Saxo-målinger"})
        continue
    summary=account_value_summary_v1(tuple(clean.assign(
        observed_at=clean["observed_at"].astype(str)).to_dict("records")))
    overview.append({"Konto":name,"Valuta":currency,
        "Siste verdi":round(float(clean.iloc[-1]["total_value"]),2),
        "Endring i kontoverdi":round(float(summary["value_change"]),2),
        "Målinger":len(clean),
        "Kvalitet":"Verifisert verdi; P/L ikke avstemt"})
st.subheader("Faktisk kontoverdi")
st.dataframe(pd.DataFrame(overview),use_container_width=True,hide_index=True)
st.caption(
    "Beløp i hver kontos egen valuta. Kontoverdiendring inkluderer "
    "eventuelle kapitaloverføringer; netto handelsgevinst vises ikke "
    "før Saxos transaksjoner og bokførte kostnader er avstemt. "
    "Målinger for ulike valutaer summeres ikke."
)

st.subheader("Kontoverdi og strategiperioder · aktive V3-kontoer")
st.caption(
    "Én graf per aktiv V3-konto. Øverst: faktisk Saxo TotalValue. "
    "Strategibåndet nederst deler tidsaksen og viser hvilken strategi "
    "som var LIVE ved hver registrerte femminuttersmåling. "
    "Hold over båndene for detaljer. Byttetidspunkter er observert, "
    "ikke verifisert eksakt. Hull i målingene interpoleres ikke."
)
try:
    active_accounts={i.account_id:i for i in load_v3_instances_v1()}
except Exception as exc:
    active_accounts={}
    st.warning("Kan ikke verifisere aktive V3-kontoer: "+type(exc).__name__)
show_other=st.checkbox(
    "Vis også Saxo-kontoer uten en aktiv V3-instans",
    value=False,key="account-truth-show-unmanaged",
)
visible_account_ids=[
    aid for aid in dict.fromkeys(frame["account_id"].astype(str))
    if aid in active_accounts or show_other
]
if not visible_account_ids:
    st.info("Ingen aktive V3-kontoer med kontomålinger. "
            "Du kan også velge å se øvrige Saxo-kontoer.")
for account_id in visible_account_ids:
    try:
        samples_for_chart=load_account_truth_v1(account_id=account_id,days=days)
        if not samples_for_chart:
            continue
        account_rows=pd.DataFrame(samples_for_chart)
        name=str(account_rows.iloc[-1]["account_name"])
        currency=str(account_rows.iloc[-1]["currency"])
        heading=f"{name} · {currency}"
        if account_id in active_accounts:
            heading+=f" · {active_accounts[account_id].market_name}"
        st.markdown(f"**{heading}**")
        fig,verified,periods=build_saxo_account_strategy_chart_v1(
            samples_for_chart,height=305)
        st.plotly_chart(fig,use_container_width=True,
                        key=f"account-strategy-timeline:{account_id}",
                        config={"displaylogo":False})
        if verified==0:
            st.warning("Ingen verifiserte Saxo-kontoverdier i denne perioden.")
        if len(samples_for_chart)>=50000:
            st.warning("Visningen kan være avkortet ved 50 000 målinger. "
                       "Velg en kortere periode.")
        # Comparison is by actually observed Saxo equity, never synthetic
        # backfilled strategy P/L. A switch/gap/multiple owners excludes the
        # delta across the boundary, and deposits remain unresolved.
        observed_windows=observed_live_nav_windows_v1(samples_for_chart)
        if observed_windows:
            with st.expander("Kontoverdiendring per observert LIVE-strategiperiode"):
                st.caption(
                    "Foreløpig evaluering av kontoverdi, IKKE dokumentert strategi-P/L. "
                    "Viser kun sammenhengende Saxo-målinger med bekreftet kvalitet "
                    "og samme entydige LIVE-strategi. Hopp ved strategibytte, "
                    "måleavbrudd og uklart eierskap tilordnes ingen strategi. "
                    "Innskudd, uttak, andre handler, finansiering og FX er "
                    "ikke avstemt. Sammenlign derfor ikke tallene direkte som nettoavkastning."
                )
                st.dataframe(pd.DataFrame([
                    {"Strategi":w.strategy_key+" · "+w.timeframe,
                     "Først observert (UTC)":w.first_observed,
                     "Sist observert (UTC)":w.last_observed,
                     "Målinger":w.observations,
                     f"Endring i Saxo TotalValue ({w.currency}), uavstemt":
                         None if w.value_change is None else round(w.value_change,2),
                     "Endring %, uavstemt":
                         None if w.value_change_pct is None else round(w.value_change_pct,2),
                     "Største observert NAV-fall %":
                         None if w.max_observed_drawdown_pct is None
                         else round(w.max_observed_drawdown_pct,2)}
                    for w in observed_windows[-100:]
                ]).iloc[::-1],use_container_width=True,hide_index=True)
        if periods:
            last=periods[-1]
            st.caption(f"Sist observert: {last.label} · "
                       f"{last.last_observed:%d.%m %H:%M} UTC. "
                       f"{len(periods)} observerte sammenhengende perioder.")
            with st.expander("Observerte strategiperioder"):
                st.dataframe(pd.DataFrame([
                    {"Først observert (UTC)":p.first_observed,
                     "Sist observert (UTC)":p.last_observed,
                     "Strategi":p.label,
                     "Marked":p.market or "Ukjent",
                     "LIVE ved observasjon":"PÅ" if p.live_armed else "AV / ukjent",
                     "Målinger":p.observations}
                    for p in periods
                ]),use_container_width=True,hide_index=True)
    except Exception as exc:
        st.error("Kan ikke vise kontograf: "+type(exc).__name__)

choices={f"{name} · {currency} [{aid[-5:]}]":aid
         for aid,name,currency in frame[["account_id","account_name","currency"]]
                                  .drop_duplicates().itertuples(index=False,name=None)}
selection=st.selectbox("Velg konto",options=list(choices),key="account-truth-selected")
data=frame[frame["account_id"]==choices[selection]].sort_values("observed_at")
good=data[data["verified"]].copy()
if good.empty:
    st.warning("Valgt konto har foreløpig ingen måling med bekreftet Saxo-beregningskvalitet.")
    st.stop()
latest=good.iloc[-1]
cols=st.columns(4)
cols[0].metric("Saxo TotalValue",f"{latest['total_value']:,.2f} {latest['currency']}")
cols[1].metric("CashBalance","—" if pd.isna(latest["cash_balance"])
               else f"{latest['cash_balance']:,.2f}")
cols[2].metric("Åpen margin-P/L","—" if pd.isna(latest["unrealized_margin_pnl"])
               else f"{latest['unrealized_margin_pnl']:+,.2f}")
cols[3].metric("Finansiering (opptjent)","—" if pd.isna(latest["financing_accruals"])
               else f"{latest['financing_accruals']:+,.2f}")
st.caption(
    f"Siste Saxo-måling: {latest['observed_at']} · "
    f"Reliability={latest['calculation_reliability']} · "
    "profitstatus: IKKE AVSTEMT (innskudd/uttak/bokførte handler mangler)."
)
st.subheader("Saxo offisiell historisk kontoperformance")
try:
    daily,official=load_official_performance_v1(
        account_id=choices[selection],days=max(90,days))
except Exception as exc:
    daily,official=(),None
    st.caption("Offisielle historiske Saxo-data kan ikke leses: "+type(exc).__name__)
if official is not None:
    if official["currency"]!=latest["currency"]:
        st.error("Saxo historisk valuta samsvarer ikke med kontobalansen; resultat skjult.")
    else:
        if official["status"]=="SAXO_REPORTED_ACCOUNT_PNL" and official["profit"] is not None:
            st.metric("Saxo rapportert kontosresultat",
                      f"{float(official['profit']):+,.2f} {official['currency']}")
        elif official["status"]=="BROKER_HISTORY_EMPTY":
            st.info("Ingen historiske resultatdata fra Saxo i valgt rapportperiode. "
                    "Dette er normalt for kontoer uten handelshistorikk; "
                    "ukjent P/L vises ikke som null.")
        else:
            st.warning("Saxo ga ikke et verifiserbart historisk resultatbeløp.")
        st.caption(
            f"Resultatet gjelder kontoen, alle instrumenter og handler, "
            f"ikke bare valgt autotrader. Forespurt periode "
            f"{official['period_from']}–{official['period_to']} · "
            f"Saxos siste registrerte handelsdag: {official.get('last_trade_day') or 'ukjent'}. "
            "Historiske resultater er Saxos EOD-tall, ikke dagens intradag-P/L."
        )
else:
    st.info("Saxo historisk resultat er ikke hentet ennå. "
            "Den uavhengige rapportinnsamlingen kjører daglig og prøver "
            "igjen dersom Saxo ennå ikke har gjort data tilgjengelige.")
if daily and (official is None or official["currency"]==latest["currency"]):
    performance=pd.DataFrame(daily)
    performance["value_date"]=pd.to_datetime(performance["value_date"],utc=True)
    performance=performance.set_index("value_date").sort_index()
    if performance["time_weighted_fraction"].notna().any():
        series=performance[["time_weighted_fraction"]].dropna()*100.
        series.columns=["Saxo akkumulert TWR %"]
        st.line_chart(series,use_container_width=True)
        st.caption(
            "Offisiell tidsvektet avkastning. Saxo inkluderer relevante "
            "finansierings- og konverteringskostnader; dette er account-wide, "
            "ikke individuell strategi-P/L."
        )
    if performance["account_value"].notna().any():
        st.markdown("**Saxo historiske dagsverdier**")
        st.line_chart(performance[["account_value"]].dropna(),
                      use_container_width=True)
        st.caption(
            "Dagsavsluttede verdier fra Saxo. Intradagdata vises separat under."
        )

st.subheader("Kontoverdi over tid")
if choices[selection] in visible_account_ids:
    st.caption("Kontografen med strategiperioder for denne kontoen vises ovenfor.")
else:
    detail_fig,_,_=build_saxo_account_strategy_chart_v1(
        tuple(data.to_dict("records")),height=350)
    st.plotly_chart(detail_fig,use_container_width=True,
                    key=f"account-strategy-detail:{choices[selection]}")

# Full as-of attribution context, not a claim that all account movements were
# produced by the currently configured V3 strategy.
context_rows=[]
market_points=[]
for row in good.itertuples(index=False):
    try:
        contexts=json.loads(row.context_json)
    except (TypeError,ValueError):
        contexts=[]
    if not isinstance(contexts,list):
        continue
    for item in contexts:
        if not isinstance(item,dict):
            continue
        ctx={
            "Saxo-måling":row.observed_at,
            "Instans":str(item.get("instance_id") or "")[:8],
            "Strategi":item.get("strategy"),
            "Periode":item.get("timeframe"),
            "Marked":item.get("market"),
            "LIVE":bool(item.get("live_armed")),
            "Markedstid":item.get("market_bar_at"),
        }
        context_rows.append(ctx)
        price=item.get("market_close")
        if isinstance(price,(int,float)) and price>0:
            market_points.append((row.observed_at,item.get("market"),
                                  float(price),float(row.total_value)))
st.subheader("Samtidig strategi- og markedsinformasjon")
if context_rows:
    contexts=pd.DataFrame(context_rows)
    st.dataframe(contexts.tail(150).iloc[::-1],use_container_width=True,hide_index=True)
    if market_points:
        market_frame=pd.DataFrame(
            market_points,columns=["timestamp","market","price","account_value"])
        for market,subset in market_frame.groupby("market"):
            subset=subset.sort_values("timestamp").drop_duplicates("timestamp")
            if len(subset)>1 and subset["price"].iloc[0]>0 and subset["account_value"].iloc[0]>0:
                compare=pd.DataFrame({
                    "Kontoverdi % (uavstemt)":100*(subset["account_value"].to_numpy()/
                                                subset["account_value"].iloc[0]-1),
                    f"{market} pris %":100*(subset["price"].to_numpy()/
                                           subset["price"].iloc[0]-1)},
                    index=subset["timestamp"])
                st.markdown(f"**Utvikling mot {market}**")
                st.line_chart(compare,use_container_width=True)
                st.caption("Relativ utvikling fra første samtidige observasjon. "
                    "Kontoendring inkluderer mulige inn-/utbetalinger; "
                    "korrelasjon er ikke kausal strategiavkastning.")
else:
    st.warning("Ingen tidslåst V3-strategikontekst lagret på denne kontoen ennå.")

st.subheader("Verifiserte V3-ordre i samme periode")
try:
    with connect() as db:
        events=db.execute("""SELECT executed_at,instance_id,market_name,
               action,side,amount,broker_order_id
               FROM autotrader_v3_execution_events
               WHERE account_id=? AND executed_at>=?
               ORDER BY executed_at DESC LIMIT 150""",
               (choices[selection],good["observed_at"].iloc[0].to_pydatetime())).fetchall()
    execution=[dict(x) for x in events]
except Exception:
    execution=[]
if execution:
    st.dataframe(pd.DataFrame(execution).rename(columns={
        "executed_at":"Tid","instance_id":"Instans-ID",
        "market_name":"Marked","action":"Handling","side":"Side",
        "amount":"Lot","broker_order_id":"Saxo ordre-ID",
    }),use_container_width=True,hide_index=True)
    st.caption("Bekreftede V3-execution events. Inkluderer ikke nødvendigvis "
               "manuelle handler, V2-handler eller alle Saxo-gebyrer.")
else:
    st.info("Ingen bekreftede V3-execution events i dette utvalget.")
