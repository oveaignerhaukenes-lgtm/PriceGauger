"""Saxo GET cost audit and archived quote spread, research only."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime,timedelta,timezone
import json

import pandas as pd
import streamlit as st

from autotrader_saxo_cost_evidence_v1 import (
    archived_bbo_spread,fetch_saxo_historical_costs,
    get_saxo_indicative_costs,simple_roundtrip_quote_friction,
)
from instrument_registry_v2 import list_subscribed_sources_v2

st.set_page_config(page_title="Saxo · Kostnadslab",layout="wide")
st.title("Saxo · Kostnadslab")
st.caption(
    "Eksakt Saxo-konto og produkt · historiske bokførte transaksjonskostnader "
    "(GET), indikativ konto-/størrelsesspesifikk handelspris (GET), "
    "og gjennomsnittlig/spiss historisk bid/ask-spread fra ekte sekundkurser."
)
st.info(
    "Ingen ordrer sendes. Dette er heller ikke Saxo PRECHECK/POST. "
    "Kostnadsillustrasjoner gjelder nåværende forhold; bokførte "
    "transaksjoner er kalenderdatoer (ikke eksakt 03:00-sesjon). "
    "En pris-spread er ikke nødvendigvis en separat Saxo-gebyrlinje."
)
try:
    sources=tuple(x for x in list_subscribed_sources_v2(provider="saxo")
                  if str(x.provider_instrument_id).isdigit())
except Exception as exc:
    st.error("Produktregisteret er ikke tilgjengelig: "+type(exc).__name__)
    st.stop()
if not sources:
    st.warning("Ingen abonnerte Saxo-produkter.")
    st.stop()
default=next((i for i,s in enumerate(sources)
              if "tech" in s.market_name.lower() or "nas" in s.market_name.lower()),0)
source=st.selectbox(
    "Eksakt instrument",sources,index=default,
    format_func=lambda x:f"{x.market_name} · {x.display_name} · "
                         f"UIC {x.provider_instrument_id}/{x.asset_type}",
)
hours=st.selectbox("Historisk bid/ask-vindu, timer",(1,3,6,12,24,72),index=4)
lookback=st.selectbox("Bokførte Saxo-dager",(1,3,7,14),index=2)
lot=st.number_input("Indikativ ordrestørrelse (lot/enheter)",
                    min_value=.01,value=.01,step=.01,format="%.2f")
st.caption(
    "Gjennomsnitt av gyldige registrerte spreads, ikke gjennomsnitt "
    "over tid uten sitater. Historisk P90 viser dyrere øyeblikk. "
    "Forhåndsdefinert handelsstørrelse er IKKE automatisk godkjent "
    "av Saxo; minimum og lotsteg må kontrolleres separat."
)

if st.button("1 · Analyser faktisk historisk spread",type="primary"):
    try:
        quote_result=archived_bbo_spread(
            uic=int(source.provider_instrument_id),hours=hours,limit=80000)
        st.session_state["saxo_cost:spread"]=(
            int(source.provider_instrument_id),hours,quote_result)
    except Exception as exc:
        st.error("Bid/ask-historikk ikke tilgjengelig: "
                 +type(exc).__name__+": "+str(exc)[:160])
saved=st.session_state.get("saxo_cost:spread")
if saved and saved[:2]==(int(source.provider_instrument_id),hours):
    bbo=saved[2]
    st.subheader("Observerte markedsfriksjoner")
    a,b,c,d=st.columns(4)
    a.metric("Gjennomsnitt spread",f"{bbo.average_points:.3f} punkter"
             if bbo.average_points is not None else "–")
    b.metric("P90 spread",f"{bbo.p90_points:.3f} punkter"
             if bbo.p90_points is not None else "–")
    c.metric("Gjennomsnitt spread",f"{bbo.mean_bps:.2f} bp"
             if bbo.mean_bps is not None else "–")
    d.metric("Gyldige kursobservasjoner",bbo.observations)
    st.caption(
        f"Fra {bbo.first_at or '–'} til {bbo.last_at or '–'} UTC. "
        f"Kurstetthet ≈ {bbo.data_density_fraction*100:.1f} % av alle sekunder "
        "i valgt klokkeperiode, ikke et bevis på full handelsdekning. "
        +("Maks antall rader ble nådd; tallene gjelder kun nyeste uttrekk."
          if not bbo.complete_request else "Hele forespurte uttrekk er innenfor datagrensen.")
    )
    point_value=st.number_input(
        "Kun indikativ friksjonsomregning: NOK per prispoeng per lot",
        min_value=.01,value=10.,step=1.,
        help="Dette er IKKE Saxo-verifisert multiplikator/FX. "
             "Kryssing av én full spread for en roundtrip er bare et estimat.")
    if bbo.average_points is not None:
        result=simple_roundtrip_quote_friction(
            spread_points=bbo.average_points,
            point_value_nok_per_lot=point_value,lots=lot)
        st.caption(
            f"Gjennomsnittlig spread som hypotetisk roundtrip-friksjon: "
            f"{result:.2f} NOK gitt **manuelt** multiplikatorgrunnlag. "
            "Ved faktisk bid/ask-fill må spread IKKE trekkes to ganger."
        )

st.subheader("Saxos faktiske kostnadsdata")
st.caption(
    "Saxo Historical Transactions: bokførte linjer og realisert P/L. "
    "Saxo tradingconditions/cost: indikativ kurtasje/holding for nåværende "
    "kurs, valgt konto og størrelse. De kan ikke legges blindt sammen."
)
if st.button("2 · Finn tilknyttede Saxo-kontoer (GET)"):
    try:
        from saxo_provider import configured_client
        from strategy_lab_v2_saxo_costs import saxobank_accounts_v2
        client=configured_client()
        if client is None:raise ValueError("Saxo OAuth ikke tilkoblet PriceGauger")
        st.session_state["saxo_cost:accounts"]=saxobank_accounts_v2(client)
    except Exception as exc:
        st.error("Saxo-kontoer kunne ikke leses: "
                 +type(exc).__name__+": "+str(exc)[:130])
accounts=st.session_state.get("saxo_cost:accounts") or ()
selected=st.multiselect(
    "Velg kontoer",accounts,
    format_func=lambda x:f"{x['account_id']} · {x['currency']}",
    max_selections=8,
    default=tuple(accounts)[:min(5,len(accounts))],
)
if st.button("3 · Hent bokførte + indikative Saxo-kostnader",
             disabled=not selected):
    try:
        from saxo_provider import configured_client
        client=configured_client()
        if client is None:raise ValueError("Saxo OAuth må være tilkoblet")
        stop=datetime.now(timezone.utc)
        start=stop-timedelta(days=int(lookback))
        rows=[];errors={}
        for account in selected:
            account_id=str(account["account_id"])
            entry=dict(account_id=account_id,currency=account["currency"])
            try:
                history=fetch_saxo_historical_costs(
                    client=client,account_key=account["account_key"],
                    account_id=account_id,uic=int(source.provider_instrument_id),
                    asset_type=str(source.asset_type),
                    start=start,end=stop)
                entry.update({
                    "Bokførte transaksjoner":history.rows,
                    "Saxo TotalCost sum":history.signed_saxo_total_cost,
                    "Kostnadsdebet (absolutt)":history.total_debits_abs,
                    "RealizedPnL sum":history.realized_pnl_sum,
                    "Kostnadsfelt mangler":history.cost_unknown_rows,
                    "Provisoriske intradag":history.incomplete_intraday_rows,
                    "Historisk valuta":history.currency,
                })
            except Exception as exc:
                errors[account_id+" historikk"]=type(exc).__name__+": "+str(exc)[:120]
            try:
                indicative=get_saxo_indicative_costs(
                    client=client,account_key=account["account_key"],
                    account_id=account_id,uic=int(source.provider_instrument_id),
                    asset_type=str(source.asset_type),amount=float(lot))
                entry.update({
                    "Kjøp indikativ kurtasje":indicative.long_commission,
                    "Selg indikativ kurtasje":indicative.short_commission,
                    "Indikativ valuta":indicative.fee_currency,
                    "Saxo pris":indicative.price,
                    "Kostnadsprobe":indicative.verification,
                })
            except Exception as exc:
                errors[account_id+" indikativ"]=type(exc).__name__+": "+str(exc)[:120]
            rows.append(entry)
        st.session_state["saxo_cost:broker"]={
            "key":(int(source.provider_instrument_id),int(lookback),float(lot),
                   tuple(sorted(x["account_id"] for x in selected))),
            "asof":stop.isoformat(),"rows":rows,"errors":errors,
            "source":"SAXO_GET_ONLY_CLIENT_ACCOUNT_PRODUCT",
        }
    except Exception as exc:
        st.error("Saxo-forespørselen mislyktes uten å sende ordre: "
                 +type(exc).__name__+": "+str(exc)[:180])
broker_result=st.session_state.get("saxo_cost:broker")
if broker_result:
    current_key=(int(source.provider_instrument_id),int(lookback),float(lot),
                 tuple(sorted(x["account_id"] for x in selected)))
    if broker_result["key"]!=current_key:
        st.warning("Valgene er endret: hent på nytt før du bruker kostnadstallene.")
    else:
        if broker_result["rows"]:
            st.dataframe(pd.DataFrame(broker_result["rows"]),
                         hide_index=True,use_container_width=True)
        if broker_result["errors"]:
            st.warning("Deler av Saxo-forespørselen mangler: "
                       "ukjente kostnader er IKKE tolket som null.")
            st.json(broker_result["errors"])
        st.caption(
            "Historisk TotalCost er Saxos bokførte transaksjonsfelt i "
            "oppgitt valuta og kan inneholde flere kostnadstyper. "
            "Ikke legg SpreadCost, kommisjon og TotalCost sammen uten "
            "å avstemme overlapp. Alle tall er knyttet til eksakt konto/UIC."
        )
export={}
if saved and saved[:2]==(int(source.provider_instrument_id),hours):
    export["spread"]=asdict(saved[2])
if broker_result and broker_result["key"]==(int(source.provider_instrument_id),
       int(lookback),float(lot),tuple(sorted(x["account_id"] for x in selected))):
    export["saxo_costs"]=broker_result
if export:
    st.download_button(
        "Eksporter kostnadsbevis (JSON)",
        json.dumps(export,ensure_ascii=False,allow_nan=False,default=str),
        file_name="pricegauger_saxo_cost_evidence.json",mime="application/json")
