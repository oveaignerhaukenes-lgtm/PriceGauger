"""Read-only HyperVigilant Chase 10s PAPER metrics in Strategy Lab v2.

The experiment uses exactly the same Saxo second BBO feed as Hyper Stochastic.
Independent prospective position tracks and full round-trip turnover costs.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import streamlit as st
from live_sim_hyper_chase_10s_v1 import (
    ARMS, VERSION, chase_snapshot_v1, MAX_QUOTE_AGE_SECONDS,
    FAST_MOVE_BPS,FILTERED_MOVE_BPS,
)
from live_sim_hyper_quotes_v1 import hyper_quote_status
from live_sim_tv_charts_v1 import render_lab_tv_series


def render_hyper_chase_v1():
    st.subheader("HyperVigilant Chase · 10 sekunder")
    st.caption(
        "PAPER-eksperiment på reelle Saxo Tech100 bid/ask-quotes. "
        "Forsøker å registrere et stort 10s-prisrykk uten å vente på "
        "MACD/Stochastic og kan gå direkte LONG ↔ SHORT ved neste "
        "faktiske ferske quote. Ingen LIVE-handel eller Saxo-ordre."
    )
    st.info(
        "Direkte flip betyr én PAPER-posisjonsovergang, men to betalte "
        "handelssider (lukk + åpne), inklusive målt bid/ask-spread og "
        "forskningsantakelser om kurtasje/slippage. Ingen garanti for "
        "at ordren ville blitt fylt slik hos Saxo."
    )
    try:
        tracks,points=chase_snapshot_v1()
        feeds=hyper_quote_status()
    except Exception as exc:
        st.warning("Sekundbasert PAPER-motor er ikke tilgjengelig: "+
                   type(exc).__name__)
        return
    if feeds:
        st.caption("Saxo quote-opptak: "+", ".join(
            f"{q['market_name']} UIC {q['provider_uic']} "
            f"({q['captured_quotes']} lagrede, siste {q['last_quote']} UTC)"
            for q in feeds[:4]))
    if not tracks:
        st.info(
            "Venter på nye, ekte omsettelige Saxo-quotes. "
            "Ved oppstart varmes signalhistorien uten historiske PAPER-handler. "
            "Markedet må ha reell dekning med omtrent ett sekund mellom quotes."
        )
        return
    names={
        "CHASE_10S_FAST":"FAST · 10s chase",
        "CHASE_10S_FILTERED":"FILTERED · kontroll",
    }
    now=datetime.now(timezone.utc)
    frame=[]
    for s in tracks:
        last=datetime.fromisoformat(str(s["last_quote"]).replace("Z","+00:00"))
        age=(now-last).total_seconds()
        frame.append({
            "Saxo UIC":s["provider_uic"],
            "Arm":names.get(s["arm"],s["arm"]),
            "Avkastning PAPER %":round(100*(s["equity"]/10000-1),3),
            "Max DD %":round(100*s["max_drawdown"],3),
            "Eksponering":s["exposure"],
            "Handler":s["trades"],"Direkte reverseringer":s["flips"],
            "Spread NOK":round(s["spread_cost_nok"],2),
            "Gebyr NOK":round(s["fees_nok"],2),
            "Slippage NOK":round(s["slippage_nok"],2),
            "Signal-til-fill (s)":s["last_fill_delay_seconds"],
            "Databrudd":s["gaps"],
            "For gamle quotes":s["stale_quotes"],
            "Kursalder (s)":round(age,1),
            "Status":("MOTTAR" if 0<=age<=MAX_QUOTE_AGE_SECONDS
                      else "INGEN FERSK SAXO-QUOTE"),
            "Siste signal":s["last_reason"],
        })
    st.dataframe(pd.DataFrame(frame),use_container_width=True,
                 hide_index=True,height=min(250,85+38*len(frame)))
    with st.expander("Signallogikk og kostnadsantakelser",expanded=False):
        st.markdown(
            f"**FAST:** 10s bevegelse, minimum {FAST_MOVE_BPS:g} basispunkter. "
            f"**FILTERED:** minimum {FILTERED_MOVE_BPS:g} basispunkter, "
            "og samme fortegn i begge halvdeler av 10s-vinduet. Begge "
            "krever tilstrekkelig ekte 1s-sampling, fersk tid, liten spread "
            "og adaptiv terskel basert på observert støy samt omsetningskostnad. "
            "Ingen ventetid mellom reverseringer.\n\n"
            "Normalisert PAPER-eksponering −1/0/+1, start 10 000. "
            "Kommisjon 2 bp og slippage 1 bp per side, i tillegg til "
            "faktisk observert bid/ask-halvspread per side. En full "
            "LONG→SHORT-flip har omsetning 2, også når den vises som "
            "én beslutning. Handler skjer først på neste observerte quote. "
            "Fersk quote kan mangle; da finnes ingen 10s-garanti."
        )
    if not points:
        st.caption("Ingen prospektive PAPER-resultatpunkter enda.")
        return
    for uic in sorted({x["provider_uic"] for x in tracks}):
        subset=[x for x in points if x["provider_uic"]==uic]
        if not subset:continue
        chart=pd.DataFrame([{
            "Tid":pd.to_datetime(p["quote_at"],utc=True),
            "Arm":names.get(p["arm"],p["arm"]),
            "Avkastning %":100*(float(p["equity"])/10000-1),
        }for p in subset])
        render_lab_tv_series(
            chart.pivot_table(index="Tid",columns="Arm",
                              values="Avkastning %",aggfunc="last").sort_index(),
            key=f"slab2:chase10:{uic}",
            title=f"HyperVigilant 10s · Saxo UIC {uic} · PAPER (%)",
        )
        trades=[p for p in subset if p["traded"]]
        if trades:
            st.markdown(f"**Siste faktiske PAPER-fills · UIC {uic}**")
            st.dataframe(pd.DataFrame([{
                "Tid (UTC)":p["quote_at"],
                "Strategi":names.get(p["arm"],p["arm"]),
                "Handling":p["action"],
                "Eksponering":p["exposure"],
                "Kurs":round(p["mid"],2),
                "Omsatt eksponering":p["turnover"],
                "Signal→fill (s)":p["signal_delay_seconds"],
                "Spread (bp)":round(p["spread_bps"],2),
                "Kostnad NOK":round(p["total_cost_nok"],2),
                "Signalbevis":p["evidence"],
            }for p in trades[-50:]][::-1]),
                use_container_width=True,hide_index=True)
    package={
        "version":VERSION,
        "caveat":"forward-only normalized PAPER, not real Saxo returns/fills",
        "arms":frame,
        "points":points,
    }
    import json
    st.download_button(
        "Eksporter 10s Chase-data til ChatGPT (JSON)",
        data=json.dumps(package,ensure_ascii=False,allow_nan=False,default=str),
        file_name="hyper_chase_10s_paper.json",mime="application/json",
        key="slab2:chase_export",
    )


__all__=["render_hyper_chase_v1"]
