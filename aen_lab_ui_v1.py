"""SIM-only AEn Core workspace: no runtime authority or Saxo mutation."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import altair as alt
import pandas as pd
import streamlit as st

from aen_replay_v1 import AEnPaperConfig, FAMILIES, TIMEFRAMES, ENGINE_VERSION, replay, prepare_replay_inputs
from live_sim_lab_store_v1 import lab_snapshot
from macd_nextgen_lab_ui_v1 import _recent_bars, _plot_reports


def _regime_contributions(report, bars, *, lookback=20):
    """Classify each return by PREVIOUS completed bars, never future outcomes."""
    closes = {str(pd.to_datetime(b.bar_time, utc=True) + pd.Timedelta(minutes=1)):
              float(b.close) for b in bars}
    ordered = sorted(closes.items())
    times = [t for t, _ in ordered]
    vals = [v for _, v in ordered]
    regimes = {}
    for i in range(lookback, len(vals)):
        history = vals[i-lookback:i]  # exclude the bar whose P/L will be scored
        displacement = history[-1] - history[0]
        travel = sum(abs(history[j] - history[j-1]) for j in range(1, len(history)))
        efficiency = abs(displacement) / travel if travel > 0 else 0
        regime = ("Sideveis" if efficiency < 0.32 else
                  "Opptrend" if displacement > 0 else "Nedtrend")
        regimes[times[i]] = regime
    prior = None
    summary = {}
    for stamp, pct, _gross, _units in report.points:
        # the signal closes at this timestamp; outcome is for the preceding bar
        regime = regimes.get(str(pd.to_datetime(stamp, utc=True)))
        if prior is not None and regime:
            slot = summary.setdefault(regime, [0, 0.0])
            slot[0] += 1
            slot[1] += pct - prior
        prior = pct
    return [{"Regime":name,"1m-barer":v[0],
             "Sum netto %-poeng (referanse)":round(v[1],4)}
            for name, v in sorted(summary.items())]


def _filled_chart(bars, report):
    # Read-only, contextual market chart; markers are SIM fills, not LIVE orders.
    if not bars:
        return
    closes = pd.DataFrame([{
        "Tid":pd.to_datetime(b.bar_time, utc=True) + pd.Timedelta(minutes=1),
        "Pris":float(b.close),
    } for b in bars])
    if closes.empty:
        return
    line = alt.Chart(closes).mark_line(color="#75a5de", strokeWidth=1.4).encode(
        x=alt.X("Tid:T", title="UTC"), y=alt.Y("Pris:Q", scale=alt.Scale(zero=False))
    )
    if report.fills:
        fills = pd.DataFrame([{
            "Tid":pd.to_datetime(t, utc=True),
            "Pris":float(price),
            "Enheter":n,
            "Hendelse":reason,
            "Tidsramme":f"{tf}m",
            "Markør":("▲"+str(n) if n>0 else "▼"+str(-n) if n<0 else "○0"),
        } for t,n,reason,tf,price in report.fills])
        markers = alt.Chart(fills).mark_text(dy=-10, fontSize=13, fontWeight="bold").encode(
            x="Tid:T", y="Pris:Q", text="Markør:N",
            color=alt.condition(alt.datum.Enheter > 0, alt.value("#24a779"),
                                alt.value("#df7771")),
            tooltip=["Tid:T","Pris:Q","Enheter:Q","Hendelse:N","Tidsramme:N"]
        )
        line = line + markers
    st.altair_chart(line.interactive(), use_container_width=True)


def render_aen_core_lab_v1():
    st.subheader("AEn Core · Adaptive Engine")
    st.caption("Ny, isolert historisk PAPER-motor. Simulering, ikke virkelig handel. "
               "Deterministisk AUTO er ikke AI-autonomi. Ingen Saxo-ordrer eller kontotilgang.")
    try:
        _, _, feeds = lab_snapshot()
    except Exception as exc:
        st.warning("AEn kan ikke hente markedskilder: "+type(exc).__name__)
        return
    if not feeds:
        st.info("Venter på canonical 1m-markedsdata.")
        return
    sources = {str(x["instrument_id"]):x for x in feeds}
    selected = st.selectbox("AEn-marked",list(sources),
                            format_func=lambda k:sources[k]["market_name"],key="aen:market")
    market = sources[selected]
    # Each market keeps its own SIM controls within this Streamlit session.
    keybase = f"aen:{selected}:"
    if "tech" not in str(market["market_name"]).lower() or "100" not in str(market["market_name"]):
        st.info("0,01 lot er verifisert som minimum for Tech100 i dette prosjektet, "
                "men ikke for dette markedet. Enhetene her er kun syntetisk PAPER-notional.")
    a,b,c,d = st.columns(4)
    signal_tf = a.selectbox("MACD-oppløsning (min)",TIMEFRAMES,index=2,key=keybase+"signal_tf")
    structure_tf = b.selectbox("HH/HL-candles (min)",TIMEFRAMES,index=2,key=keybase+"structure_tf")
    days = c.selectbox("Analyseperiode (dager)",(1,3,7,14),index=1,key=keybase+"days")
    auto = d.toggle("AUTO timeframe",value=False,key=keybase+"auto",
                    help="Regelbasert PAPER-controller med hysterese. AI har ingen kontroll i denne versjonen.")
    capkey=keybase+"max_units"
    st.session_state.setdefault(capkey,1)
    cols = st.columns([2,1,1,2,2])
    cols[0].markdown(f"**Tillatt eksponering:** {st.session_state[capkey]} × 0,01 lot")
    if cols[1].button("↓ −1",key=keybase+"less",disabled=st.session_state[capkey]<=1):
        st.session_state[capkey]-=1
    if cols[2].button("↑ +1",key=keybase+"more",disabled=st.session_state[capkey]>=20):
        st.session_state[capkey]+=1
    scale = cols[3].toggle("Structure Scaling",value=True,key=keybase+"scale")
    impulse = cols[4].toggle("Impulse Detector",value=False,key=keybase+"impulse")
    ladder_col, pulse_col = st.columns([1,2])
    ladder = ladder_col.toggle("1m→2m→5m bekreftelse",value=False,key=keybase+"ladder",
                    help="Valgfri 0,01-lot pulsprobe, deretter én enhet på 2m og 5m bekreftelse.")
    pulse_pct = pulse_col.slider("Minst 1m-puls (%)",0.05,1.0,0.12,0.01,
                                 disabled=not ladder,key=keybase+"pulse")
    settings = st.columns(3)
    left = settings[0].number_input("Swing: venstre candles",min_value=1,max_value=8,value=2,key=keybase+"left")
    right = settings[1].number_input("Swing: bekreftelsescandles",min_value=1,max_value=8,value=2,key=keybase+"right")
    hysteresis = settings[2].slider("MACD hysterese",0.0,2.0,0.5,0.1,key=keybase+"hysteresis")
    x,y,z = st.columns(3)
    impulse_pct = x.number_input("Impulse candle (%)",min_value=0.05,max_value=5.0,
                                 value=0.30,step=0.05,disabled=not impulse,key=keybase+"impulse_pct")
    vol_factor = y.number_input("Relativt volum ×",min_value=1.0,max_value=5.0,
                                value=1.4,step=0.1,disabled=not impulse,key=keybase+"vol")
    wait_bars = z.number_input("Maks retrace-venting (min)",min_value=1,max_value=30,
                               value=3,disabled=not impulse,key=keybase+"wait")
    with st.expander("Kostnader og risikoforutsetninger",expanded=False):
        charge=st.toggle("Inkluder kostnader",value=True,key=keybase+"costs")
        f,s,notional=st.columns(3)
        fee=f.number_input("Kommisjon per side (%)",0.0,2.0,0.08,0.01,format="%.3f",
                           key=keybase+"fee",disabled=not charge)
        spread=s.number_input("Full spread (%)",0.0,1.0,0.01,0.005,format="%.3f",
                              key=keybase+"spread",disabled=not charge)
        nominal=notional.number_input("SIM-notional per 0,01 lot (× NAV)",0.01,1.0,0.20,0.01,
                                      key=keybase+"unit_exposure")
        st.caption("0,08 %/side, 0,01 % spread og notional/NAV er FORUTSETNINGER – ikke "
                   "bekreftede Saxo-priser eller reell kontraktseksponering. "
                   "Fremtidig LIVE krever instrumentspesifikk NOK-/marginmodell.")
    choices=st.multiselect("Sammenlign strategier",FAMILIES,default=FAMILIES,
                           key=keybase+"families",max_selections=4)
    if not choices:
        st.info("Velg minst én AEn-strategi.")
        return
    try:
        anchor=min(datetime.now(timezone.utc),
                   datetime.fromisoformat(str(market["last_bar_time"]).replace("Z","+00:00"))
                   +timedelta(minutes=1))
        since=anchor-timedelta(days=int(days))
        bars=_recent_bars(int(selected),(since-timedelta(days=10)).isoformat(),anchor.isoformat())
        if not bars:
            st.warning("Ingen kanoniske 1m-data for dette markedet.")
            return
        configs=[AEnPaperConfig(
            family=family,minutes=int(signal_tf),structure_minutes=int(structure_tf),
            pivot_left=int(left),pivot_right=int(right),max_units=int(st.session_state[capkey]),
            adaptive=auto,structure_scaling=scale,confirmation_ladder=ladder,
            pulse_min_pct=float(pulse_pct),impulse_enabled=impulse,
            impulse_pct=float(impulse_pct),volume_factor=float(vol_factor),
            retrace_wait_bars=int(wait_bars),hysteresis_ratio=float(hysteresis),
            unit_exposure=float(nominal),costs_enabled=charge,
            commission_side_bps=fee*100,quoted_spread_bps=spread*100
        ) for family in choices]
        prepared=prepare_replay_inputs(bars,configs[0])
        reports=[replay(cfg,bars,started_at=since,prepared=prepared) for cfg in configs]
    except Exception as exc:
        st.error("AEn replay ble avbrutt: "+type(exc).__name__+" · "+str(exc)[:180])
        return
    reports.sort(key=lambda r:(-r.return_pct,r.identity))
    st.caption(f"Felles datasett · {since:%d.%m %H:%M}–{anchor:%d.%m %H:%M} UTC · {ENGINE_VERSION}. "
               "For hver endring beregnes alle kurver på nytt. Historiske resultater er ikke forward P/L.")
    st.dataframe(pd.DataFrame([{
        "Strategi":r.label, "Netto SIM %":round(r.return_pct,3),
        "Brutto %":round(r.gross_pct,3), "Maks DD %":round(r.max_drawdown_pct,3),
        "Kostnader (% av start)":round(r.total_cost_pct,3),
        "Ordreendringer":r.executions,"Omsatte enheter":r.turnover_units,
        "Aktiv / tillatt":f"{abs(r.points[-1][3]) if r.points else 0}/{st.session_state[capkey]}",
        "Timeframe-bytter":len(r.timeframe_changes),
    } for r in reports]),hide_index=True,use_container_width=True)
    _plot_reports([SimpleNamespace(identity=r.identity,label=r.label,
                                   return_pct=r.return_pct,
                                   points=tuple((t,n,g) for t,n,g,_ in r.points))
                   for r in reports])
    variants={r.label:r for r in reports}
    name=st.selectbox("Vis markedspris, SIM-fills og eksponering",list(variants),
                      key=keybase+"detail")
    focus=variants[name]
    _filled_chart(bars,focus)
    if focus.points:
        exposure=pd.DataFrame([{"Tid":pd.to_datetime(t,utc=True),"Enheter":units}
                               for t,_net,_gross,units in focus.points]).set_index("Tid")
        st.line_chart(exposure, height=180, use_container_width=True)
    with st.expander("Revisjon: alle signaler, fills og tidsrammebytter"):
        st.caption("En flat-posisjon bekreftes her i SIM. Den er IKKE Saxo-verifisert.")
        st.dataframe(pd.DataFrame(focus.decisions,
                     columns=["Ferdig candle UTC","Årsak","Fra enheter","Til enheter","MACD-min"]),
                     hide_index=True,use_container_width=True)
        st.dataframe(pd.DataFrame(focus.fills,
                     columns=["Neste åpen UTC","Etter-fill enheter","Årsak","MACD-min","Fyllpris"]),
                     hide_index=True,use_container_width=True)
        st.dataframe(pd.DataFrame(focus.timeframe_changes,
                     columns=["Besluttet UTC","Fra min","Til min","Årsak"]),
                     hide_index=True,use_container_width=True)
    with st.expander("Regimer · bidrag til nettoresultat"):
        st.caption("Retning/effektivitet basert på tidligere 20 fullførte 1m closes. "
                   "Bidragene er additive prosentpoeng, ikke regimevis sammensatt avkastning.")
        st.dataframe(pd.DataFrame(_regime_contributions(focus,bars)),
                     hide_index=True,use_container_width=True)
    st.warning("AEn er et tilbakeblikk med forenklet neste-bar-fill, uten faktisk Saxo-slippage, "
               "finansiering, intrabar stops, marginvalidering eller framoverskuende PAPER-ledger. "
               "Ikke tolk lønnsomhet eller enhetsstørrelse som LIVE-klar.")
