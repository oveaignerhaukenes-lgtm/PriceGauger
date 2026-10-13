"""Read-only V2 strategy research: no V2 account enrolment or broker authority."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

from autotrader_engine_identity_v1 import ENGINE_V2, engine_for_strategy_key_v1
from autotrader_strategy_catalog_v2 import AUTOTRADER_STRATEGIES_V2
from autotrader_v2_flip_reference_lab_v1 import reference_v2_flip, SUPPORTED_V2_FLIP_MINUTES
from macd_nextgen_lab_ui_v1 import _recent_bars, _plot_reports
from macd_nextgen_paper_v1 import MacdConfig, replay
from live_sim_lab_store_v1 import lab_snapshot


def v2_strategy_catalog_v1():
    """All V2 strategy identities, never silently migrate them to V3."""
    return tuple(x for x in AUTOTRADER_STRATEGIES_V2
                 if engine_for_strategy_key_v1(x.key)==ENGINE_V2)


@st.fragment(run_every="60s")
def render_v2_strategy_lab_v1():
    st.subheader("V2 strategies · referanse og portabilitet")
    st.caption("V2-motorens MACD Flip-signaler ligger fortsatt i repoet. "
               "Dagens Railway worker kjører imidlertid ikke V2-dispatcheren. "
               "Her kjøres kun historisk, kostnadsjustert PAPER-replay — ingen Saxo-ordrer.")
    st.warning("V2 LIVE er **ikke reaktivert**. En strategi som ble positiv i SHADOW "
               "blir ikke automatisk positiv med virkelig fill, spread eller finansiering.")
    with st.expander("Hele V2-strategikatalogen",expanded=False):
        catalog=v2_strategy_catalog_v1()
        st.caption(f"{len(catalog)} gamle V2-identiteter beholdes. "
                   "De fleste er ikke signalverifisert mot den nye LAB-motoren. "
                   "Bare ren MACD Flip er støttet i denne referanse-sammenligningen.")
        st.dataframe(pd.DataFrame([{
            "Navn":x.label,
            "Strategi-ID":x.key,
            "Signalreferanse":"MACD Flip referanse"
                if x.key in {
                    "macd-1m-flip-control-shadow-v1",
                    "macd-2m-flip-control-shadow-v1",
                    "macd-5m-flip-control-shadow-v1",
                    "macd-15m-flip-control-shadow-v1",
                    "macd-30m-long-short-v1",
                } else "Ikke paritetsverifisert",
        } for x in catalog]),hide_index=True,width="stretch")

    try:
        _experiments, _memory, feeds=lab_snapshot()
    except Exception as exc:
        st.error("Mangler Live-Sim-kildedata: "+type(exc).__name__)
        return
    if not feeds:
        st.info("Venter på kanoniske markedsdata.")
        return
    options={str(x["instrument_id"]):x for x in feeds}
    chosen=st.selectbox("Marked",tuple(options),
                        format_func=lambda k:options[k]["market_name"],
                        key="v2ref:instrument")
    frames=st.multiselect("V2 MACD Flip (minutter)",
                          SUPPORTED_V2_FLIP_MINUTES,default=(2,5),
                          key="v2ref:timeframes")
    one,two,three,four=st.columns(4)
    days=one.selectbox("Analyseperiode (dager)",(1,3,7,14),index=1,key="v2ref:days")
    with_cost=two.toggle("Inkluder kostnader",value=True,key="v2ref:costs")
    commission=three.number_input("Avgift per side (%)",min_value=0.0,max_value=2.0,
                                  value=0.08,step=0.01,key="v2ref:commission",
                                  disabled=not with_cost)
    spread=four.number_input("Full spread (%)",min_value=0.0,max_value=1.0,
                             value=0.01,step=0.005,key="v2ref:spread",
                             disabled=not with_cost)
    compare=st.toggle("Sammenlign med ny MACD Flip / Hold",
                      value=True,key="v2ref:compare")
    st.caption("V2-ref: MACD 12/26/9 fra V2-kontrollens lukket-bar signalmodell, "
               "mål 100 % LONG/SHORT. Estimert neste-1m-open PAPER fill. "
               "Saxo kan fylle senere fordi CLOSE → bekreftet FLAT → OPEN "
               "er sekvensielt. 0,08 % er foreløpig antatt avgift per handlet side, "
               "**ikke** verifisert Saxo-pris. Kostnader inkluderer halv antatt spread per side.")
    if not frames:
        st.info("Velg minst én V2-signalperiode.")
        return
    try:
        end=min(datetime.now(timezone.utc),datetime.fromisoformat(
            str(options[chosen]["last_bar_time"]).replace("Z","+00:00"))
                +timedelta(minutes=1))
        since=end-timedelta(days=int(days))
        bars=_recent_bars(int(chosen),(since-timedelta(days=14)).isoformat(),end.isoformat())
        if not bars:
            st.info("Ingen canonical market bars i valgt periode.")
            return
        reports=[]
        table=[]
        for tf in frames:
            old=reference_v2_flip(bars,timeframe_minutes=int(tf),started_at=since,
                                  costs_enabled=with_cost,commission_side_bps=commission*100,
                                  quoted_spread_bps=spread*100)
            reports.append(old)
            table.append({
                "Motor":"V2 MACD Flip ref","Min":tf,
                "Netto PAPER %":round(old.return_pct,3),
                "Brutto %":round(old.gross_pct,3),
                "Maks DD %":round(old.max_drawdown_pct,3),
                "Estimert Saxo-ordrer":old.estimated_broker_orders,
                "Målendringer":old.executions,
                "Kostnad % av start":round(old.total_cost_pct,3),
            })
            if compare:
                new=replay(MacdConfig(minutes=int(tf),flip=True,
                                      hold_before_flip=True,pyramide=False,
                                      trailing=False),bars,started_at=since,
                           costs_enabled=with_cost,commission_side_bps=commission*100,
                           quoted_spread_bps=spread*100)
                # Label and identity are distinct: never represent two different
                # replay engines as one strategy, even for equal signal timeframes.
                reports.append(new)
                table.append({
                    "Motor":"NextGen MACD Flip/Hold","Min":tf,
                    "Netto PAPER %":round(new.return_pct,3),
                    "Brutto %":round(new.gross_pct,3),
                    "Maks DD %":round(new.max_drawdown_pct,3),
                    "Estimert Saxo-ordrer":new.estimated_broker_orders,
                    "Målendringer":new.executions,
                    "Kostnad % av start":round(new.total_cost_pct,3),
                })
    except Exception as exc:
        st.error("V2-sammenligning feilet: "+type(exc).__name__)
        return
    st.caption("Tidsvindu UTC: "+since.strftime("%d.%m %H:%M")+" – "+
               end.strftime("%d.%m %H:%M")+" · felles prisgrunnlag")
    st.dataframe(pd.DataFrame(table).sort_values("Netto PAPER %",ascending=False),
                 hide_index=True,width="stretch")
    st.caption("Kurver sortert etter netto PAPER-avkastning. Forskjeller mellom "
               "V2-ref og NextGen skyldes policy, signalens timing og replay-kontrakt. "
               "Dette dokumenterer **ikke** identisk LIVE-ordreutførelse.")
    _plot_reports(sorted(reports,key=lambda p:(-p.return_pct,p.identity)))
