"""Tech100 second impulse event study — actual stored BBO, RESEARCH only."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime,timedelta,timezone
import json

import pandas as pd
import streamlit as st

from database import connect
from instrument_registry_v2 import list_subscribed_sources_v2
from tech100_second_impulse_research_v1 import (
    MAX_ROWS,LOOKBACKS_SECONDS,THRESHOLDS_BPS,HORIZONS_SECONDS,
    chronological_split_at,prepare_second_quotes,study_thresholds,
    summarize_thresholds,
)

st.set_page_config(page_title="Tech100 sekundimpulser · PriceGauger",layout="wide")
st.title("Tech100 · Sekundimpulser")
st.caption("Hendelsesanalyse på faktiske lagrede Saxo bid/ask-observasjoner.")
st.warning(
    "RESEARCH, ikke LIVE. Dette er frekvenser fra faktisk kursdata, "
    "ikke verifiserte handler eller dokumentert netto avkastning. "
    "Mulig slippage, finansiering, latency og market impact er ikke "
    "avstemt mot Saxo. Ingen ordre eller kontoinnstillinger endres."
)
st.markdown(
    "**Hypotese:** Når kursen har beveget seg minst en terskel over "
    "5/10/20/30 sekunder, øker sjansen for videre bevegelse i samme retning. "
    "Vi måler både fortsettelsen *etter* terskelen og hvor mye den "
    "påfølgende kursen tar tilbake etter toppen/bunnen."
)

try:
    available=tuple(x for x in list_subscribed_sources_v2(provider="saxo")
                    if ("TECH" in x.market_name.upper() or "NAS" in x.market_name.upper())
                    and str(x.provider_instrument_id).isdigit())
except Exception as exc:
    st.error("Klarte ikke åpne abonnert Saxo-instrumentoversikt: "+type(exc).__name__)
    st.stop()
if not available:
    st.info("Fant ikke et abonnert Saxo Tech100 UIC.")
    st.stop()
source=st.selectbox(
    "Eksakt Saxo-marked / UIC",available,
    format_func=lambda s:f"{s.market_name} · {s.display_name} · UIC {s.provider_instrument_id}",
)
a,b,c=st.columns(3)
hours=a.selectbox("Observasjonsperiode (klokketimer)",(3,6,12,24),index=1)
lookbacks=b.multiselect("Sekunder som utløser terskel",LOOKBACKS_SECONDS,
                         default=(5,10,20))
minimum=c.number_input(
    "Minste antall separate impulser for indikativ vurdering",
    min_value=5,max_value=500,value=25,step=5
)

if st.button("Analyser lagrede sekundkurser",type="primary"):
    try:
        end=datetime.now(timezone.utc)
        start=end-timedelta(hours=hours)
        with connect() as db:
            rows=db.execute(
                """SELECT quote_at,received_at,bid,ask FROM lsim_hyper_quotes_1s
                   WHERE provider_uic=? AND quote_at>=? AND quote_at<=?
                   ORDER BY quote_at LIMIT ?""",
                (int(source.provider_instrument_id),start.isoformat(),
                 end.isoformat(),MAX_ROWS+1)
            ).fetchall()
        if len(rows)>MAX_ROWS:
            raise ValueError("For stor datamengde. Velg færre timer.")
        if len(rows)<500:
            raise ValueError(
                "Fant ikke nok faktisk lagrede sekundkurser på denne UIC-en. "
                "Dette kan skyldes manglende aktiv Saxo-stream eller tynn dekning."
            )
        sessions=prepare_second_quotes([dict(x) for x in rows])
        cutoff=chronological_split_at(sessions)
        events=study_thresholds(
            sessions,lookbacks=tuple(lookbacks),
            thresholds=THRESHOLDS_BPS,horizons=HORIZONS_SECONDS,
            chronological_cutoff=cutoff,
        )
        aggregates=summarize_thresholds(events,chronological_cutoff=cutoff)
        st.session_state["second_impulse_report"]={
            "key":(int(source.provider_instrument_id),hours,tuple(lookbacks)),
            "asof":end.isoformat(),"cutoff":cutoff.isoformat(),
            "raw":len(rows),"sessions":len(sessions),
            "usable_quotes":sum(len(x) for x in sessions),
            "events":events,"groups":aggregates,
            "uic":int(source.provider_instrument_id),
        }
    except (ValueError,TypeError,OverflowError) as exc:
        st.session_state.pop("second_impulse_report",None)
        st.warning(str(exc))
    except Exception as exc:
        st.session_state.pop("second_impulse_report",None)
        st.error("Klarte ikke hente/analysere faktiske kurser: "+type(exc).__name__)

r=st.session_state.get("second_impulse_report")
if r:
    if r["key"]!=(int(source.provider_instrument_id),hours,tuple(lookbacks)):
        st.info("Valgene er endret. Kjør analysen på nytt.")
    else:
        st.subheader("Datadekning og kvalitet")
        c1,c2,c3,c4=st.columns(4)
        c1.metric("Lagrede BBO-rader",f"{r['raw']:,}")
        c2.metric("Godkjente sammenhengende sitater",f"{r['usable_quotes']:,}")
        c3.metric("Sammenhengende dataserier",str(r["sessions"]))
        c4.metric("Separate terskelhendelser",
                  str(len(r["events"])//len(HORIZONS_SECONDS)))
        st.caption(
            f"Første 70 % av observerte gyldige sitater er kalibreringsdel, "
            f"siste 30 % holdout. Grense UTC {r['cutoff']}. "
            "Rader med ugyldig bid/ask, gamle sitater eller datagap "
            "gir ingen fabrikkert sekundpris. "
            "Impulser holdes adskilt med minst 125 sekunder per terskeltest."
        )

        st.subheader("Videre bevegelse og tilbakeslag")
        horizon=st.select_slider(
            "Utfallet målt så mange sekunder ETTER terskelbruddet",
            options=HORIZONS_SECONDS,value=120,
        )
        fields=[]
        for g in r["groups"]:
            if g.horizon_seconds != horizon:continue
            fields.append({
                "Periode": "Kalibrering 70 %" if g.sample=="FØRSTE_70PCT"
                           else "Holdout 30 %",
                "Impuls-vindu":f"{g.lookback_seconds}s",
                "Terskel":f"{g.threshold_bps:g} bp",
                "Uavhengige hendelser":g.events,
                "Videre etter spread > 0":(
                    round(g.profitable_fraction*100,1)
                    if g.profitable_fraction is not None else None),
                "Først med videre ½-terskel (%)":(
                    round(g.continued_half_threshold_fraction*100,1)
                    if g.continued_half_threshold_fraction is not None else None),
                "Median netto etter bid/ask (bp)":(
                    round(g.median_net_bps,2)
                    if g.median_net_bps is not None else None),
                "Median videre maks (bp)":(
                    round(g.median_max_continuation_bps,2)
                    if g.median_max_continuation_bps is not None else None),
                "Median sekunder til maksimum":(
                    round(g.median_time_to_peak_seconds,1)
                    if g.median_time_to_peak_seconds is not None else None),
                "Median tilbakeslag fra maksimum (%)":(
                    round(g.median_retraced_from_peak_pct,1)
                    if g.median_retraced_from_peak_pct is not None else None),
                "Median spread (bp)":(
                    round(g.median_spread_bps,2)
                    if g.median_spread_bps is not None else None),
            })
        if fields:
            df=pd.DataFrame(fields)
            st.dataframe(df,use_container_width=True,hide_index=True)
            holdout=[g for g in r["groups"] if g.sample=="SISTE_30PCT"
                     and g.horizon_seconds==horizon and g.events>=minimum]
            if holdout:
                best=max(holdout,key=lambda x:x.median_net_bps
                         if x.median_net_bps is not None else float("-inf"))
                st.info(
                    f"Deskriptivt høyeste holdout-median blant grupper med "
                    f"minst {minimum} hendelser: {best.lookback_seconds}s / "
                    f"{best.threshold_bps:g} bp, {best.events} hendelser, "
                    f"{best.median_net_bps:+.2f} bp etter oppgitt spreadproxy. "
                    "Dette er valgt på holdout og er dermed ikke en "
                    "uavhengig fremtidstest eller anbefalt LIVE-terskel."
                )
            else:
                st.warning(
                    "For få hendelser i holdout til å sammenligne tersklene "
                    "med valgt minstekrav. Utvid historikken før konklusjoner."
                )
        else:
            st.warning("Ingen fullstendig kvalifiserte terskelbrudd på denne perioden.")

        st.caption(
            "1 basispunkt (bp) = 0,01 % prisendring. "
            "Videre maks måles FRA terskelbruddet, ikke fra starten av impulsen. "
            "Tilbakeslagsprosent er hvor mye av påfølgende maksimal viderebevegelse "
            "som er tatt tilbake ved valgt horisont; den kan overstige 100 %. "
            "Hypotetisk netto prisretning benytter senere mottatt BBO for inngang "
            "og bid/ask ved målehorisonten, uten garanti om at broker kunne fylle "
            "ordren. Terskelvinner velges aldri som LIVE-konfigurasjon her."
        )
        st.download_button(
            "Eksporter aggregerte resultater (JSON)",
            json.dumps({
                "schema":"TECH100_SECOND_IMPULSE_EVENT_STUDY_V1",
                "uic":r["uic"],"asof_utc":r["asof"],
                "cutoff_utc":r["cutoff"],
                "saved_quotes":r["raw"],"usable_quotes":r["usable_quotes"],
                "segments":r["sessions"],
                "groups":[asdict(g) for g in r["groups"]],
                "notes":"Research-only, non-overlap/next-received BBO proxy, no Saxo fills.",
            },ensure_ascii=False,allow_nan=False),
            file_name="tech100_second_impulse_event_study.json",
            mime="application/json",
        )
else:
    st.caption("Velg historikk og trykk Analyser for å se faktiske resultatverdier.")
