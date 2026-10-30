"""PriceGauger Algorithm Lab — safely generate, edit and replay PAPER models.

This page never executes user/AI Python, changes LIVE config, or posts Saxo orders.
Stored 1m and 1s BBO sources are read through explicitly bounded SELECT queries.
"""
from __future__ import annotations

from datetime import datetime, date, time, timedelta, timezone
from dataclasses import asdict
import json

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from algorithm_lab_v1 import PRESETS, MAX_BARS, LabCosts, replay_algorithm, validate_plan, utc
from algorithm_lab_ai_v1 import propose_algorithm, ALGORITHM_DESIGN_PROMPT
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from database import connect
from instrument_registry_v2 import list_subscribed_sources_v2
from strategy_lab_v2_ai import LabAIError

st.set_page_config(page_title="Algoritmelab", layout="wide")
st.title("Algoritmelab · Directional Specialists")
st.caption("Generer algoritmeforslag med AI, rediger en trygg modelloppskrift, "
           "kjør simulering på lagret Saxo 1m-historikk, og sammenlign PAPER-P/L. "
           "Ingen LIVE-ordre, ingen kjøring av AI-generert Python.")
st.info("Gjeldende v1 bruker ferdige **1m-prisbarer** til beslutninger og "
        "neste faktiske 1m-open til PAPER-fills. 1s Saxo BBO kan inspiseres nedenfor, "
        "men brukes ennå ikke i tilbakeberegningen. Impulse Collector er derfor "
        "foreløpig en 1m-baseline, ikke en validert 10s-strategi. "
        "Kostnadene er scenarioestimater, ikke reelle Saxo-fills.")

try:
    sources = list_subscribed_sources_v2(provider="saxo")
except Exception as exc:
    sources = ()
    st.warning("Instrumentregisteret er utilgjengelig: " + type(exc).__name__)
if not sources:
    st.warning("Ingen aktive Saxo-instrumenter. Abonner på instrument og 1m-historikk først.")
    st.stop()

c0, c1 = st.columns((1.3, 2))
with c0:
    markets = sorted({s.market_name for s in sources})
    market = st.selectbox("Marked", markets, key="alg:market")
with c1:
    candidates = [s for s in sources if s.market_name == market]
    source = st.selectbox(
        "Eksakt lagret Saxo-produkt", candidates,
        format_func=lambda s: f"{s.display_name} · UIC {s.provider_instrument_id} · {s.asset_type}",
        key="alg:instrument")

st.subheader("1 · Strategi og algoritme")
left, right = st.columns((1.5, 1))
with left:
    preset = st.selectbox("Start med mal", tuple(PRESETS), key="alg:preset")
    if st.session_state.get("alg:last_preset") != preset:
        st.session_state["alg:editable_plan"] = json.dumps(PRESETS[preset], indent=2,
                                                             ensure_ascii=False)
        st.session_state["alg:last_preset"] = preset
    proposed = st.session_state.pop("alg:pending_plan", None)
    if proposed is not None:
        st.session_state["alg:editable_plan"] = json.dumps(proposed, indent=2,
                                                             ensure_ascii=False)
    plan_text = st.text_area(
        "Modellkode (validert JSON-oppskrift, ikke kjørbar Python)",
        height=290, key="alg:editable_plan",
        help="Endre lookback, entry_bps, exit_bps, fade_bps, max_hold, regime_rule og retning.")
    try:
        plan = validate_plan(json.loads(plan_text))
        st.success("Modellen er gyldig og klar for PAPER.")
    except (ValueError, TypeError) as exc:
        plan = None
        st.error("Modellfeil: " + str(exc))
with right:
    st.markdown("**AI-assistert modellutvikling**")
    user_request = st.text_area(
        "Beskriv endring eller ny idé",
        value=("Lag en énveis regimefølgende strategi der ferdig 30m MACD "
               "bestemmer retning, men 1m momentum avgjør entry og flat."),
        height=145, key="alg:ai_request")
    if st.button("Foreslå ny modell med AI", type="secondary",
                 disabled=plan is None, key="alg:generate"):
        with st.spinner("Ber AI om en validert modelloppskrift"):
            try:
                # Only the current selected instrument's historic closed prices.
                now = datetime.now(timezone.utc)
                recent = CanonicalMarketBarStoreV2().load_instrument_range(
                    instrument_id=int(source.instrument_id),
                    start=now-timedelta(minutes=45), end=now-timedelta(minutes=2),
                    limit=45)
                observed = [{"at": utc(b.bar_time).isoformat(), "close": b.close}
                            for b in recent][-24:]
                suggestion = propose_algorithm(
                    request=user_request, current_plan=plan,
                    market=source.market_name, observed_closes=observed)
                st.session_state["alg:pending_plan"] = suggestion["plan"]
                st.session_state["alg:ai_rationale"] = suggestion["rationale"]
                st.session_state["alg:ai_notes"] = suggestion["test_notes"]
                st.rerun()
            except (LabAIError, ValueError, TypeError) as exc:
                st.error(str(exc))
            except Exception as exc:
                st.error("AI-tjenesten er utilgjengelig: " + type(exc).__name__)
    if st.session_state.get("alg:ai_rationale"):
        st.markdown("**Modellbegrunnelse**")
        st.write(st.session_state["alg:ai_rationale"])
        st.caption(st.session_state.get("alg:ai_notes", ""))
    with st.expander("Vis systemprompt / modellkontrakt"):
        st.code(ALGORITHM_DESIGN_PROMPT, language="text")

st.subheader("2 · Periode og kostnader")
now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
d1, d2, d3, d4 = st.columns(4)
start_date = d1.date_input("Fra (UTC)", now.date()-timedelta(days=2), key="alg:start_date")
start_time = d2.time_input("Klokkeslett fra (UTC)", time(0, 0), key="alg:start_time")
end_date = d3.date_input("Til (UTC)", now.date(), key="alg:end_date")
end_time = d4.time_input("Klokkeslett til (UTC)", now.time(), key="alg:end_time")
start = datetime.combine(start_date, start_time, tzinfo=timezone.utc)
end = datetime.combine(end_date, end_time, tzinfo=timezone.utc)

k1, k2, k3, k4 = st.columns(4)
capital = k1.number_input("Startkapital NOK", min_value=1., value=10000., step=1000.,
                          key="alg:capital")
lot = k2.number_input("Antall lot", min_value=.001, value=.01, step=.01, format="%.3f",
                      key="alg:lot")
point_value = k3.number_input("NOK per indekspoeng per 1 lot", min_value=.001,
                              value=100., step=10., key="alg:point_value")
spread = k4.number_input("Spread (basispoeng)", min_value=0., value=2., step=.5,
                         key="alg:spread")
k5, k6, k7 = st.columns(3)
slippage = k5.number_input("Slippage (bp, hver utførelse)", min_value=0., value=1.,
                           step=.5, key="alg:slippage")
commission = k6.number_input("Fast gebyr NOK per utførelse", min_value=0., value=0.,
                             step=1., key="alg:commission")
fee_bps = k7.number_input("Variabelt gebyr (bp per side)", min_value=0., value=0.,
                          step=.5, key="alg:fee_bps")
st.caption("Angitt punktverdi, lot, spread og kostnader er **manuelle "
           "forutsetninger**, ikke verifiserte Saxo-kontovilkår. "
           "Resultatet inkluderer ikke finansiering eller valutakursendringer.")

run = st.button("Kjør simulering / beregn netto P/L", type="primary",
                disabled=plan is None, key="alg:run")
if run:
    try:
        if end <= start or end-start > timedelta(days=6):
            raise ValueError("Velg et sammenhengende vindu over 0 og høyst 6 døgn.")
        # 72h warmup before the START is separate from the measured P/L interval.
        bars = CanonicalMarketBarStoreV2().load_instrument_range(
            instrument_id=int(source.instrument_id),
            start=start-timedelta(hours=72), end=end,
            limit=MAX_BARS+1)
        if len(bars) > MAX_BARS:
            raise ValueError("For mange råbarer. Forkort tidsvinduet.")
        costs = LabCosts(point_value_nok=point_value,
                         starting_nav_nok=capital, lot_size=lot,
                         spread_bps=spread, slippage_bps=slippage,
                         commission_nok=commission, variable_fee_bps=fee_bps)
        result = replay_algorithm(plan=plan, bars=bars, costs=costs,
                                  start_at=start, end_at=end)
        st.session_state["alg:last_result"] = (
            {"market": market, "uic": str(source.provider_instrument_id),
             "start": start.isoformat(), "end": end.isoformat(),
             "plan": plan, "costs": asdict(costs)}, result)
    except (ValueError, TypeError) as exc:
        st.error(str(exc))
    except Exception as exc:
        st.error("PAPER-kjøring mislyktes: " + type(exc).__name__)

saved = st.session_state.get("alg:last_result")
if saved is not None:
    meta, result = saved
    st.subheader("3 · Simuleringsresultat")
    st.caption(f"Resultat fra siste kjøring: {meta['market']} · UIC {meta['uic']} · "
               f"{meta['start']} – {meta['end']}. Endringer krever ny kjøring.")
    cols = st.columns(5)
    cols[0].metric("Netto PAPER-P/L", f"{result.pnl_nok:+,.2f} NOK")
    cols[1].metric("Avkastning", f"{result.return_pct:+.2f}%")
    cols[2].metric("Maks drawdown", f"{result.drawdown_pct:.2f}%")
    cols[3].metric("PAPER-utførelser", str(len(result.trades)))
    cols[4].metric("Modellerte kostnader", f"{result.total_cost_nok:,.2f} NOK")
    if result.warmup_30m_bars < 35 and meta["plan"]["kind"] == "trend":
        st.warning("MACD30 ble ikke varmet opp med minst 35 sammenhengende "
                   "ferdige 30m-barer i siste dataserie. Få eller ingen handler "
                   "kan derfor være forventet, ikke bevis på svakt signal.")
    if result.gaps:
        st.warning(f"{result.gaps} databrudd. PAPER-eksponering ble satt til FLAT "
                   "ved siste observerte close i stedet for å finne på gap-priser.")
    plot = go.Figure()
    plot.add_trace(go.Scatter(
        x=[x.at for x in result.points], y=[x.close for x in result.points],
        mode="lines", name="Saxo lagret 1m CLOSE"))
    for kind, symbol, color in (("OPEN", "triangle-up", "#1ca176"),
                                ("FLAT", "triangle-down", "#e09b32"),
                                ("GAP_FLAT", "x", "#cc4455"),
                                ("END_FLAT", "x", "#888888")):
        ev = [t for t in result.trades if t.action == kind]
        if ev:
            plot.add_trace(go.Scatter(
                x=[t.at for t in ev], y=[t.price for t in ev],
                mode="markers", name=kind,
                marker={"symbol": symbol, "size": 10, "color": color}))
    plot.update_layout(title="Pris og beregnede handler", height=430,
                       xaxis_title="UTC", yaxis_title="Instrumentpris",
                       hovermode="x unified")
    st.plotly_chart(plot, use_container_width=True)
    equity = pd.DataFrame([
        {"UTC": p.at, "PAPER NAV (NOK)": p.nav_nok, "Position": p.position,
         "Signal": p.signal, "Regime 30m": p.regime}
        for p in result.points])
    st.line_chart(equity.set_index("UTC")[["PAPER NAV (NOK)"]], height=260)
    with st.expander("Ordrejournal · beregnede fills", expanded=True):
        st.dataframe(pd.DataFrame([asdict(t) for t in result.trades]),
                     use_container_width=True, hide_index=True)
    st.download_button(
        "Eksporter PAPER-resultat (CSV)",
        equity.to_csv(index=False).encode("utf-8"),
        file_name="algorithm_lab_paper_nav.csv", mime="text/csv",
        key="alg:download")

st.subheader("4 · Rådata og siste registrerte BBO")
st.caption("Lesetilgang til lagret prisdata for valgt Saxo-UIC, ikke "
           "ukontrollert tilgang til kontoer, private tabeller eller Saxo-ordre.")

@st.cache_data(ttl=10, show_spinner=False)
def recent_bbo(uic: int):
    # A bounded, parameterized SELECT. Do not expose database access to AI code.
    with connect() as db:
        rows = db.execute(
            """SELECT quote_at, bid, ask
               FROM lsim_hyper_quotes_1s
               WHERE provider_uic=?
               ORDER BY quote_at DESC LIMIT 240""",
            (uic,)).fetchall()
    return tuple(dict(row) for row in reversed(rows))

try:
    quotes = recent_bbo(int(source.provider_instrument_id))
    if quotes:
        quote_data = pd.DataFrame(quotes)
        quote_data["quote_at"] = pd.to_datetime(quote_data["quote_at"], utc=True)
        age = (datetime.now(timezone.utc)-quote_data["quote_at"].iloc[-1].to_pydatetime()).total_seconds()
        st.caption(f"Siste lagrede Saxo BBO: {quote_data['quote_at'].iloc[-1]} "
                   f"({age:.0f} sek gammelt). Ikke anta sanntid dersom data er eldre.")
        st.line_chart(quote_data.set_index("quote_at")[["bid", "ask"]],
                      height=220)
        st.dataframe(quote_data.tail(30), use_container_width=True,
                     hide_index=True)
    else:
        st.info("Ingen 1s Saxo BBO lagret for dette instrumentet.")
except Exception as exc:
    st.warning("1s-datakilden er utilgjengelig: " + type(exc).__name__)

if saved is not None:
    with st.expander("Siste kjøringsmodell / eksakte testforutsetninger"):
        st.json(saved[0])
st.caption("Neste utviklingssteg: isolert kode-sandbox uten Saxo-/DB-hemmeligheter, "
           "sekundbasert event-replay med ordrebokspredning og lagring av "
           "versjonerte eksperimenter. Denne versjonen kjører bare den "
           "strengt validerte algoritmeoppskriften.")
