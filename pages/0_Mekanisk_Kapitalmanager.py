"""Mechanical V3 allocation manager experiment: deterministic, read-only PAPER."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime,timedelta,timezone
import json

import pandas as pd
import streamlit as st

from autotrader_v3_config_v1 import load_autotrader_config_v3
from autotrader_v3_execution_policy_v1 import load_execution_policy_v3
from autotrader_v3_instance_registry_v1 import load_v3_instances_v1
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from instrument_registry_v2 import list_subscribed_sources_v2
from mechanical_capital_manager_v1 import replay_mechanical_allocator
from mechanical_capital_manager_observer_v1 import (
    SUPPORTED_SHADOW_KEYS, latest_contiguous_completed_1m_v1,
    shadow_observer_from_completed_bars_v1,
)

st.set_page_config(page_title="Mekanisk kapitalmanager · PAPER",layout="wide")
st.title("Mekanisk kapitalmanager · 15 min · PAPER")
st.caption(
    "Eksisterende V3-eksponeringsslider brukes som øvre, manuelt valgt grense. "
    "Denne forskningssiden endrer IKKE slideren, ordrene eller LIVE."
)
st.warning(
    "Forsøksregel: ±1 % observerresultat på 15 minutter endrer ønsket "
    "eksponering med ±10 prosentpoeng av den manuelle rammen; "
    "−10 % skygge-drawdown gir mål 0. Dette er IKKE en garantert "
    "maksimal tapsgrense. Faktisk eksisterende LIVE-posisjon lukkes "
    "ikke automatisk. Ved 0 % fortsetter PAPER-observatøren."
)
st.caption(
    "Observatøren bruker faktisk lagret 1m Tech100 OHLC og deterministiske V3 "
    "strategiregler, men forenklet 1× priseksponering med oppgitt teoretisk "
    "handelspåslag. Ingen Saxo-fills, CFD-gearing, finansiering, "
    "kontantstrømmer eller faktisk konto-NAV inngår. "
    "Ikke bruk resultatene som mål for realisert LIVE-avkastning."
)

try:
    sources = tuple(x for x in list_subscribed_sources_v2(provider="saxo")
                    if ("TECH" in x.market_name.upper() or "NAS" in x.market_name.upper())
                    and str(x.provider_instrument_id).isdigit())
    instances = load_v3_instances_v1()
except Exception as exc:
    st.error("Kunne ikke hente eksakt V3-register: " + type(exc).__name__)
    st.stop()
if not sources:
    st.info("Ingen abonnert Tech100 UIC i Saxo-registeret.")
    st.stop()
source = st.selectbox(
    "Historisk marked",sources,
    format_func=lambda x: (
        f"{x.market_name} · {x.display_name} · UIC {x.provider_instrument_id}"
    ),key="mm:source",
)
available = tuple(
    x for x in instances
    if x.instrument_id == source.instrument_id and x.uic == int(source.provider_instrument_id)
)
if not available:
    st.info("Ingen V3-instanser på dette instrumentet. Lesning av LIVE er ikke mulig.")
    st.stop()
by_id = {x.instance_id:x for x in available}
selected_ids = st.multiselect(
    "Instanser (maks fire)",tuple(by_id),
    default=tuple(by_id)[:min(4,len(by_id))],
    format_func=lambda key: f"{by_id[key].market_name} · {key[:8]}",
    max_selections=4,key="mm:instances",
)
if not selected_ids:
    st.stop()
configs = {key:load_autotrader_config_v3(key) for key in selected_ids}
policies = {key:load_execution_policy_v3(key) for key in selected_ids}
chosen = {}
for key in selected_ids:
    config = configs[key]
    current = config.strategy_key
    initial = SUPPORTED_SHADOW_KEYS.index(current) if current in SUPPORTED_SHADOW_KEYS else 0
    col1,col2 = st.columns([2,1])
    chosen[key] = col1.selectbox(
        "Skyggestrategi · "+key[:8],SUPPORTED_SHADOW_KEYS,
        index=initial,key=f"mm:strategy:{key}",
    )
    policy = policies[key]
    if policy:
        col2.metric("Manuell slider (maks)",f"{policy.exposure_pct:g} %")
    else:
        col2.warning("Ingen LIVE-ramme; PAPER benytter 100 % maksimum")
a,b,c = st.columns(3)
hours=a.selectbox("1m-historikk", (6,12,24,48), index=1,
                  format_func=lambda n:f"Siste {n} timer",key="mm:hours")
cost=b.slider("Hypotetisk rundturkost (bps)",0.,50.,8.,1.,
              key="mm:cost")
initial=c.slider("Nøytral PAPER-andel av slider",10,100,50,5,
                 key="mm:neutral")
turnover = st.slider(
    "Ekstra PAPER-kost for managerens allokeringsendring (bps)",
    0.,30.,0.,1.,key="mm:turnover",
)
if st.button("Kjør mekanisk 15-minutters manager · PAPER",type="primary"):
    try:
        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=hours)
        raw = CanonicalMarketBarStoreV2().load_instrument_range(
            instrument_id=int(source.instrument_id),start=start,end=end,
            limit=6001
        )
        if len(raw)>6000:
            raise ValueError("For mange 1m-barer; bruk kortere periode.")
        bars = latest_contiguous_completed_1m_v1(raw,asof=end)
        if len(bars)<135:
            raise ValueError(
                "For få sammenhengende fullførte 1m-barer etter siste markedsgap. "
                "Minst 135 minutter kreves for 15m-manager og oppvarming."
            )
        streams=[]
        for key in selected_ids:
            policy=policies[key]
            streams.append(shadow_observer_from_completed_bars_v1(
                bars,instance_id=key,strategy_key=chosen[key],
                manual_slider_pct=float(policy.exposure_pct if policy else 100),
                cost_roundtrip_bps=float(cost),
            ))
        replay = replay_mechanical_allocator(
            streams,initial_fraction=initial/100.,
            turnover_cost_bps=turnover,
        )
        st.session_state["mm:report"]=dict(
            fingerprint=(source.instrument_id,tuple(selected_ids),
                         tuple(chosen.values()),hours,cost,initial,turnover),
            replay=replay,streams=streams,captured=len(raw),
            closed=len(bars),at=end.isoformat(),
        )
    except ValueError as exc:
        st.session_state.pop("mm:report",None)
        st.error(str(exc))
    except Exception as exc:
        st.session_state.pop("mm:report",None)
        st.error("Kunne ikke beregne PAPER-data: "+type(exc).__name__)
r=st.session_state.get("mm:report")
if r and r["fingerprint"]!=(
    source.instrument_id,tuple(selected_ids),tuple(chosen.values()),
    hours,cost,initial,turnover
):
    st.info("Innstillingene er endret – kjør forsøket på nytt.")
elif r:
    t=r["replay"]
    st.caption(f"{r['captured']} kanoniske barer hentet, {r['closed']} "
               f"fullførte sammenhengende 1m-barer, siste kjøring {r['at']} UTC.")
    if t.status!="PAPER_ONLY":
        st.warning("Utilstrekkelig felles data: "+t.status)
    else:
        st.subheader("Mekanisk ønsket kapitalandel per instans")
        latest = {x.instance_id:x for x in t.decisions}
        rows=[{
            "Instans":key[:8],
            "PAPER-strategi":chosen[key],
            "Manuelt tak (%)":latest[key].cap_pct,
            "Forslått disponering (%)":latest[key].suggested_exposure_pct,
            "Skyggeretur siste 15m (%)":round(latest[key].shadow_return_15m_pct,4),
            "Skygge-DD (%)":round(latest[key].shadow_drawdown_pct,3),
            "Status":latest[key].state,
        } for key in selected_ids if key in latest]
        st.dataframe(pd.DataFrame(rows),hide_index=True,use_container_width=True)
        history = pd.DataFrame([
            {"Tid":x.at,"Instans":x.instance_id[:8],
             "PAPER disponering (%)":x.suggested_exposure_pct}
            for x in t.decisions
        ])
        if not history.empty:
            st.line_chart(
                history.pivot_table(index="Tid",columns="Instans",
                                    values="PAPER disponering (%)"),
                use_container_width=True,
            )
        curves = pd.DataFrame([
            {"Tid":at,"Mekanisk PAPER":value}
            for at,value in t.portfolio_equity
        ] + [
            {"Tid":at,"Fast nøytral PAPER":value}
            for at,value in t.fixed_equity
        ])
        if not curves.empty:
            st.subheader("PAPER-porteføljekurve mot fast startvekt")
            st.line_chart(
                pd.DataFrame({
                    "Mekanisk PAPER":[v for _,v in t.portfolio_equity],
                    "Fast nøytral PAPER":[v for _,v in t.fixed_equity],
                },index=[k for k,_ in t.portfolio_equity]),
                use_container_width=True,
            )
        if t.correlations:
            st.subheader("Samvariasjon mellom strategiene")
            st.dataframe(pd.DataFrame([
                {"Modell A":a,"Modell B":b,"15m-korrelasjon":coef}
                for a,b,coef in t.correlations
            ]),hide_index=True,use_container_width=True)
            if any(c>=.8 for _,_,c in t.correlations):
                st.warning(
                    "Sterk positiv sammenheng i PAPER-strategiene. "
                    "De er ikke uavhengige risikokilder selv om kontoene er forskjellige."
                )
        for line in t.notes:
            st.caption(line)
    st.download_button(
        "Eksporter mekanisk PAPER-manager (JSON)",
        json.dumps({
            "status":t.status,"as_of":r["at"],
            "instrument_id":source.instrument_id,
            "observed_bars":r["closed"],"interval_minutes":15,
            "decisions":[{**asdict(x),"at":x.at.isoformat()} for x in t.decisions],
            "correlations":t.correlations,
            "note":t.notes,
        },ensure_ascii=False,allow_nan=False),
        file_name="pricegauger_manager_paper_15m.json",
        mime="application/json",
    )
