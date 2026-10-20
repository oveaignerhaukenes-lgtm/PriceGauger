"""Strategy Lab v2 account performance; authoritative Saxo NAV + strategy epochs."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from autotrader_saxo_account_truth_v1 import load_account_truth_v1
from autotrader_saxo_strategy_timeline_v1 import (
    build_saxo_account_strategy_chart_v1,
    observed_live_nav_windows_v1,
)
from live_sim_tv_charts_v1 import render_lab_tv_series
from strategy_lab_v2_replay import utc


def _overlay_frame_v2(samples,results:dict):
    reliable=[r for r in samples
              if str(r.get("calculation_reliability") or "").lower()=="ok"
              and float(r.get("total_value") or 0)>0]
    if not reliable:return pd.DataFrame()
    reliable.sort(key=lambda x:utc(x["observed_at"]))
    base=float(reliable[0]["total_value"])
    data={
        "Saxo kontoverdi % · uavstemt":pd.Series(
            [100*(float(r["total_value"])/base-1) for r in reliable],
            index=pd.DatetimeIndex([utc(r["observed_at"]) for r in reliable]),
        )
    }
    for name,result in results.items():
        if not result.points:continue
        start=float(result.points[0].nav_nok)
        if start<=0:continue
        data["PAPER · "+name]=pd.Series(
            [100*(p.nav_nok/start-1) for p in result.points],
            index=pd.DatetimeIndex([p.at for p in result.points]),
        )
    return pd.concat(data,axis=1).sort_index()


def render_account_performance_v2(*,sim_results:dict)->None:
    st.subheader("Kontoprestasjon · Saxo-fasit")
    st.caption(
        "Én graf per valgt Saxo-konto. Nederste tidsbånd viser hvilken V3 "
        "strategi som faktisk var observert LIVE ved hvert femminuttsutvalg. "
        "Byttetidspunktene er observerte intervaller, ikke eksakte ordretider."
    )
    days=st.selectbox("Kontohistorikk",(1,3,7,14,30,90,180),index=4,
                       key="slab2:accountdays")
    try:
        overview=load_account_truth_v1(days=days)
    except Exception as exc:
        st.error("Saxo-kontodata utilgjengelig: "+type(exc).__name__);return
    known={}
    for row in overview:
        known[str(row["account_id"])]=row
    if not known:
        st.info("Ingen Saxo TotalValue-målinger i den valgte perioden.");return
    options={f"{row['account_name']} · {row['currency']} · …{aid[-4:]}":aid
             for aid,row in known.items()}
    selected=st.multiselect(
        "Velg kontoer",list(options),
        default=list(options)[:min(2,len(options))],
        max_selections=6,key="slab2:accounts",
    )
    overlay_selection=st.multiselect(
        "PAPER-strategier å sammenligne med Saxo-kontoverdi",
        tuple(sim_results),default=tuple(sim_results)[:2],
        max_selections=6,key="slab2:overlay",
        help="Kurvene normaliseres separat til prosent. Dette beviser ikke "
             "at PAPER og konto hadde samme kapital eller eksponering.",
    )
    for label in selected:
        aid=options[label]
        try:
            samples=load_account_truth_v1(account_id=aid,days=days)
            if not samples:continue
            st.markdown("#### "+label)
            fig,verified,epochs=build_saxo_account_strategy_chart_v1(
                samples,height=390)
            st.plotly_chart(fig,use_container_width=True,
                            key="slab2:saxo:"+aid)
            if not verified:
                st.warning("Ingen verifiserte kontomålinger for denne kontoen")
            else:
                latest=next((x for x in reversed(samples)
                             if str(x["calculation_reliability"]).lower()=="ok"),None)
                if latest:
                    st.caption(
                        f"Siste Saxo TotalValue: {float(latest['total_value']):,.2f} "
                        f"{latest['currency']} · {latest['observed_at']} UTC. "
                        "Endringen kan omfatte kontantoverføringer, FX og manuelle handler."
                    )
            periods=observed_live_nav_windows_v1(samples)
            if periods:
                st.dataframe(pd.DataFrame([{
                    "Strategi":w.strategy_key,"Marked":w.market,
                    "Fra (observert)":w.first_observed,
                    "Til (observert)":w.last_observed,
                    "Saxo NAV-endring % (uavstemt)":w.value_change_pct,
                    "Målinger":w.observations,
                }for w in reversed(periods[-45:])]),
                    use_container_width=True,hide_index=True)
            selected_replays={key:sim_results[key] for key in overlay_selection}
            if selected_replays:
                frame=_overlay_frame_v2(samples,selected_replays)
                if not frame.empty:
                    st.caption(
                        "Sammenligning: Saxo NAV % (IKKE avstemt for cashflows) "
                        "og PAPER avkastning % fra individuelle starttidspunkt, "
                        "på felles UTC-akse. Historikk må overlappe for kausal sammenligning."
                    )
                    render_lab_tv_series(
                        frame,key="slab2:overlay:"+aid,
                        title="Saxo NAV og valgte PAPER-strategier · prosent")
        except Exception as exc:
            st.warning(
                "Kontovisning kunne ikke tegnes for valgt konto: "
                +type(exc).__name__
            )


__all__=["render_account_performance_v2","_overlay_frame_v2"]
