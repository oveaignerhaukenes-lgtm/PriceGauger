"""New independent MACD family PAPER workspace. Legacy experiments stay untouched."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from live_sim_lab_store_v1 import lab_snapshot
from macd_nextgen_paper_v1 import MacdConfig, replay, SUPPORTED_MINUTES, ENGINE_VERSION


@st.cache_data(ttl=60, show_spinner=False)
def _recent_bars(instrument_id: int, start_iso: str, end_iso: str):
    return CanonicalMarketBarStoreV2().load_instrument_range(
        instrument_id=int(instrument_id),
        start=start_iso, end=end_iso, limit=40000,
    )


def _plot_reports(reports, *, key: str = "nextgen-macd-reports"):
    """Shared TradingView navigation; source curves remain unmodified."""
    from live_sim_tv_charts_v1 import render_lab_tv_series
    pivot = pd.DataFrame()
    for report in reports:
        if not report.points:
            continue
        name = report.label
        frame = pd.DataFrame(
            [(pd.to_datetime(at, utc=True), float(net))
             for at, net, _gross in report.points],
            columns=["Tid", name],
        ).drop_duplicates(subset="Tid").set_index("Tid")[[name]].sort_index()
        pivot = frame if pivot.empty else pivot.join(frame, how="outer")
    if pivot.empty:
        st.caption("Ingen ferdige resultatpunkter i valgt periode.")
        return
    render_lab_tv_series(pivot, key=key,
                         title="Netto PAPER-resultater (%) · dra, zoom og knip")


@st.fragment(run_every="60s")
def render_nextgen_macd_lab_v1():
    st.subheader("Nye strategier · MACD")
    st.caption("NextGen v1 · isolert PAPER-replay på faktiske ferdige 1m-markedsbarer. "
               "Ingen LIVE-ordre. Endring av brytere beregner alle valgte signalperioder på nytt.")
    try:
        _existing, _memory, feeds = lab_snapshot()
    except Exception as exc:
        st.warning("Markedsfeed kan ikke leses fra Live-Sim Lab: "+type(exc).__name__)
        return
    if not feeds:
        st.info("Venter på markedsdata fra Live-Sim Lab.")
        return

    feed_options={str(x["instrument_id"]):x for x in feeds}
    source=st.selectbox("Marked",list(feed_options),format_func=lambda k:feed_options[k]["market_name"],
                        key="nextgen:source")
    feed=feed_options[source]
    periods=st.multiselect("Perioder som skal sammenlignes (minutter)",SUPPORTED_MINUTES,
                           default=(2,5,10),key="nextgen:periods")
    c1,c2,c3,c4=st.columns(4)
    flip=c1.toggle("Flip",value=True,key="nextgen:flip",
                   help="Nytt kryss reverserer vanlig posisjon, men pyramide går først FLAT.")
    hold=c2.toggle("Hold before flip",value=True,key="nextgen:hold",
                   help="Ikke trapp ned når histogramimpulsen svekkes innen samme MACD-regime.")
    pyramid=c3.toggle("Pyramide",value=False,key="nextgen:pyramid",
                      help="Bygg én tranche ved positiv impuls. Motsatt regime lukker ALT til FLAT.")
    trail=c4.toggle("Trailing",value=False,key="nextgen:trail",disabled=hold,
                    help="Bare uten Hold: trapp ned i samme regime ved svekket impuls.")
    effective_trail=trail and not hold
    if hold and trail:
        st.caption("Trailing er inaktiv når Hold before flip er på.")
    cfg_help=("Pyramide + motsatt MACD-signal → FLAT, deretter gjenoppbygging fra minste "
              "tranche først etter neste ferdige signallys.")
    st.caption(cfg_help)
    c5,c6,c7,c8=st.columns([1.0,1.1,1.3,1.0])
    days=c5.selectbox("Analyseperiode (dager)",(1,3,7,14),index=1,key="nextgen:days")
    tranches=c6.number_input("Maks trancher",min_value=1,max_value=20,value=5,
                             step=1,disabled=not (pyramid or effective_trail),key="nextgen:tranches")
    charge=c7.toggle("Inkluder kostnader",value=True,key="nextgen:costs")
    c8.caption("0,08 % er en foreløpig brukerantakelse, ikke bekreftet Saxo-sats.")
    cp1,cp2=st.columns(2)
    fee_pct=cp1.number_input("Avgift per side (%)",min_value=0.0,max_value=2.0,
                             value=0.08,step=0.01,format="%.3f",key="nextgen:fee",disabled=not charge)
    spread_pct=cp2.number_input("Full kjøp/salg-spread (%)",min_value=0.0,max_value=1.0,
                                value=0.01,step=0.005,format="%.3f",key="nextgen:spread",disabled=not charge)
    st.caption("Ved reversering beregnes **to sider**: lukking + åpning. "
               "SIM fyller til neste 1m-åpning; faktisk slippage, finansiering og Saxo-fill "
               "er ikke modellert. Dette er historisk PAPER-replay, ikke LIVE-resultat eller uavhengig forwardtest.")
    if not periods:
        st.info("Velg minst én signalperiode.")
        return
    try:
        anchor=min(datetime.now(timezone.utc),datetime.fromisoformat(
            str(feed["last_bar_time"]).replace("Z","+00:00"))+timedelta(minutes=1))
        since=anchor-timedelta(days=int(days))
        bars=_recent_bars(int(source),(since-timedelta(days=7)).isoformat(),anchor.isoformat())
        if not bars:
            st.info("Ingen kanoniske markedsbarer i valgt tidsrom.")
            return
        reports=[replay(MacdConfig(minutes=int(tf),flip=flip,hold_before_flip=hold,
                                   pyramide=pyramid,trailing=effective_trail,
                                   max_tranches=int(tranches)),bars,started_at=since,
                        costs_enabled=charge,commission_side_bps=fee_pct*100,
                        quoted_spread_bps=spread_pct*100)
                 for tf in periods]
    except Exception as exc:
        st.error("NextGen SIM kunne ikke beregnes: "+type(exc).__name__)
        return
    reports.sort(key=lambda result:(-result.return_pct,result.identity))
    st.caption("Delt datavindu: "+since.strftime("%d.%m %H:%M")+"–"+
               anchor.strftime("%d.%m %H:%M")+" UTC · motor "+ENGINE_VERSION)
    table=pd.DataFrame([{
        "Strategi":p.label,
        "Netto SIM %":round(p.return_pct,3),
        "Brutto %":round(p.gross_pct,3),
        "Maks DD %":round(p.max_drawdown_pct,3),
        "SIM-endringer":p.executions,
        "Est. Saxo-ordrer":p.estimated_broker_orders,
        "Est. kostnad % av start":round(p.total_cost_pct,3),
        "Signalbarer":p.completed_signal_bars,
    } for p in reports])
    st.dataframe(table,hide_index=True,use_container_width=True)
    st.caption("Dra grafen for å panorere, bruk musehjul/knip for å zoome; velg tidsvindu øverst. Klikk strateginavn for å skjule/åpne kurver.")
    _plot_reports(reports, key=f"nextgen:{source}")
