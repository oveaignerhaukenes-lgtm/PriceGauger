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
from algorithm_lab_ticks_v1 import MAX_QUOTES, replay_tick_impulses
from algorithm_lab_ai_v1 import propose_algorithm, ALGORITHM_DESIGN_PROMPT
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from database import connect
from instrument_registry_v2 import list_subscribed_sources_v2
from strategy_lab_v2_ai import LabAIError
from algorithm_lab_catalog_v2 import catalog_manifest, catalog_context
from algorithm_lab_versions_v2 import new_research_key, save_experiment, list_experiments
from algorithm_lab_sandbox_v2 import standalone_worker_ready, execute_in_isolated_container
from algorithm_lab_python_ai_v2 import propose_python_research, DEFAULT_CODE
from algorithm_lab_python_replay_v2 import replay_directions
from strategy_lab_v2_saxo_costs import (
    saxobank_accounts_v2, saxo_replay_costs_v2, verified_replay_costs_v2,
)

st.set_page_config(page_title="Algoritmelab", layout="wide")
st.title("Algoritmelab · Directional Specialists")
st.caption("Generer algoritmeforslag med AI, rediger en trygg modelloppskrift, "
           "kjør simulering på lagret Saxo 1m-historikk, og sammenlign PAPER-P/L. "
           "Ingen LIVE-ordre, ingen kjøring av AI-generert Python.")
st.info("To separate PAPER-klokker: 1m-replay fra ekte ferdige OHLC-candles "
        "(fill tidligst neste 1m-open), og impuls-replay fra ekte lagret Saxo "
        "1s bid/ask (fill tidligst neste registrerte quote). Ingenting interpoleres. "
        "For historiske 1m-fills er spread modellert; 1s bruker observert bid/ask. "
        "P/L er scenario, ikke Saxo-verifiserte fills eller finansieringskostnad.")

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
    st.download_button(
        "Eksporter modelloppskrift (.json)",
        data=json.dumps(plan, indent=2, ensure_ascii=False) if plan else "{}",
        file_name="algorithm_lab_model.json", mime="application/json",
        disabled=plan is None, key="alg:saveplan")
    uploaded_plan = st.file_uploader(
        "Importer tidligere modelloppskrift", type=("json",),
        key="alg:importplan")
    if uploaded_plan is not None and st.button("Åpne importert modell", key="alg:loadplan"):
        try:
            imported = validate_plan(json.loads(
                uploaded_plan.getvalue().decode("utf-8")))
            st.session_state["alg:pending_plan"] = imported
            st.rerun()
        except (UnicodeError, ValueError, TypeError) as exc:
            st.error("Kun gyldige, trygge modelloppskrifter kan importeres: " + str(exc))
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
                    market=source.market_name, observed_closes=observed,
                    sampling_mode=st.session_state.get("alg:replay_mode", "1m"))
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
mode = st.selectbox(
    "Simuleringsklokke",
    ("1m OHLC · strategi-baseline", "1s Saxo BBO · impuls-replay")
    if plan and plan["kind"] == "impulse" else
    ("1m OHLC · strategi-baseline",),
    key="alg:replay_mode")
if mode.startswith("1s"):
    st.caption("I 1s-modus betyr lookback og max_hold **sekunder**, ikke minutter. "
               "Prøv lookback=10 og max_hold=60 for en 10s-impulsmodell. "
               "Krever faktisk lagrede BBO-priser gjennom valgt periode.")
else:
    st.caption("I 1m-modus betyr lookback og max_hold ettminuttsbarer. "
               "Impulse Collector i denne modusen er en 1m-baseline.")
now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
d1, d2, d3, d4 = st.columns(4)
start_date = d1.date_input("Fra (UTC)", now.date()-timedelta(days=2), key="alg:start_date")
start_time = d2.time_input("Klokkeslett fra (UTC)", time(0, 0), key="alg:start_time")
end_date = d3.date_input("Til (UTC)", now.date(), key="alg:end_date")
end_time = d4.time_input("Klokkeslett til (UTC)", now.time(), key="alg:end_time")
start = datetime.combine(start_date, start_time, tzinfo=timezone.utc)
end = datetime.combine(end_date, end_time, tzinfo=timezone.utc)

with st.expander("Saxo GET-only · kostnadskalibrering"):
    st.caption("Konto, pris, spread, valutakonvertering og gebyr er "
               "indikative NÅ, ikke historiske fills.")
    if st.button("Hent tilgjengelige kontoer (GET)", key="alg:get_accounts"):
        try:
            from saxo_provider import configured_client
            client = configured_client()
            if client is None:
                raise ValueError("Ingen tilkoblet Saxo GET-klient.")
            st.session_state["alg:saxo_accounts"] = saxobank_accounts_v2(client)
        except Exception as exc:
            st.error("GET-kontoer ikke tilgjengelig: " + type(exc).__name__)
    accounts = st.session_state.get("alg:saxo_accounts", ())
    if accounts:
        account = st.selectbox("Konto for modellkostnader", accounts,
                               format_func=lambda x: "…" + x["account_id"][-4:]
                               + " · " + x["currency"], key="alg:saxo_account")
        if st.button("Kalibrer fra Saxo GET", key="alg:calibrate"):
            try:
                from saxo_provider import configured_client
                client = configured_client()
                if client is None:
                    raise ValueError("Saxo utilgjengelig.")
                raw = saxo_replay_costs_v2(client, source=source,
                                            account=account, quantity=.01)
                verified = verified_replay_costs_v2(raw)
                st.session_state["alg:point_value"] = float(verified.point_value_nok)
                st.session_state["alg:spread"] = float(verified.spread_bps)
                st.session_state["alg:commission"] = float(verified.fixed_fee_nok)
                st.session_state["alg:lot"] = float(verified.lot_step)
                st.session_state["alg:cost_evidence"] = verified.source
                st.rerun()
            except Exception as exc:
                st.error("Saxo kunne ikke verifisere kostnadene: " + str(exc)[:240])
if st.session_state.get("alg:cost_evidence"):
    st.caption("Nåtidsscenario: " + st.session_state["alg:cost_evidence"]
               + " (historisk spread og FX er ikke verifisert).")

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
k8, k9 = st.columns(2)
fin_long = k8.number_input("Long finansiering (% p.a.)", min_value=0.,
                           max_value=100., value=0., step=.5, key="alg:finlong")
fin_short = k9.number_input("Short finansiering (% p.a.)", min_value=0.,
                            max_value=100., value=0., step=.5, key="alg:finshort")
st.caption("Punktverdi, lot, slippage, finansiering og gebyr er scenariovalg. "
           "1m-modus modellerer spread fra feltet; 1s-modus bruker "
           "observert historisk bid/ask-spread og ignorerer feltet spread (bp). "
           "NOK-punktverdien bruker en konstant FX-forutsetning, ikke historisk valutakursserie.")

run = st.button("Kjør simulering / beregn netto P/L", type="primary",
                disabled=plan is None, key="alg:run")
if run:
    try:
        if end <= start:
            raise ValueError("Slutt må være etter start.")
        costs = LabCosts(point_value_nok=point_value,
                         starting_nav_nok=capital, lot_size=lot,
                         spread_bps=spread, slippage_bps=slippage,
                         commission_nok=commission, variable_fee_bps=fee_bps,
                         financing_long_annual_pct=fin_long,
                         financing_short_annual_pct=fin_short)
        if mode.startswith("1s"):
            if end-start > timedelta(hours=4):
                raise ValueError("1s-replay: velg maksimalt 4 timer.")
            with connect() as db:
                quote_rows = db.execute(
                    """SELECT quote_at, bid, ask FROM lsim_hyper_quotes_1s
                       WHERE provider_uic=? AND quote_at>=? AND quote_at<?
                       ORDER BY quote_at ASC LIMIT ?""",
                    (int(source.provider_instrument_id),
                     (start-timedelta(seconds=45)).isoformat(),
                     end.isoformat(), MAX_QUOTES+1)).fetchall()
            quotes = tuple(dict(x) for x in quote_rows)
            if len(quotes) > MAX_QUOTES:
                raise ValueError("For mange 1s-observasjoner. Forkort vinduet.")
            result = replay_tick_impulses(
                plan=plan, quotes=quotes, costs=costs,
                start_at=start, end_at=end)
        else:
            if end-start > timedelta(days=6):
                raise ValueError("1m-replay: velg høyst 6 døgn.")
            # 72h pre-window indicator warmup, never part of reported P/L.
            bars = CanonicalMarketBarStoreV2().load_instrument_range(
                instrument_id=int(source.instrument_id),
                start=start-timedelta(hours=72), end=end,
                limit=MAX_BARS+1)
            if len(bars) > MAX_BARS:
                raise ValueError("For mange råbarer. Forkort tidsvinduet.")
            result = replay_algorithm(plan=plan, bars=bars, costs=costs,
                                      start_at=start, end_at=end)
        run_metadata = {"market": market, "uic": str(source.provider_instrument_id),
                        "start": start.isoformat(), "end": end.isoformat(),
                        "plan": plan, "costs": asdict(costs), "mode": mode}
        st.session_state["alg:last_result"] = (run_metadata, result)
        previous_runs = st.session_state.get("alg:experiment_history", [])
        st.session_state["alg:experiment_history"] = (
            [{"at": datetime.now(timezone.utc).isoformat(),
              "label": preset, "metadata": run_metadata, "result": result}]
            + previous_runs)[:8]
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
    st.caption(f"Finansieringsscenario: {result.financing_nok:,.2f} NOK. "
               "Brukerdefinert årlig sats for observert eksponeringstid.")
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
        mode="lines", name=("Saxo lagret BBO mid" if meta.get("mode", "").startswith("1s")
                              else "Saxo lagret 1m CLOSE")))
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

st.subheader("4 · Kronologisk train / out-of-sample-test")
st.caption("En automatisk deling av historikken: hold parameterne uendret "
           "mens testperioden kjøres. Hvis du optimaliserer etter å ha sett "
           "testresultatet, er perioden ikke lenger en uavhengig test.")
split_pct = st.slider("Andel treningsperiode (%)", min_value=50,
                      max_value=85, value=70, step=5, key="alg:split")
if saved is not None and st.button("Kjør treningsperiode og urørt testperiode",
                                   key="alg:run_oos"):
    try:
        meta, _ = saved
        if meta["uic"] != str(source.provider_instrument_id):
            raise ValueError("Velg samme instrument som i siste simuleringskjøring.")
        measured_start, measured_end = utc(meta["start"]), utc(meta["end"])
        split = measured_start+(measured_end-measured_start)*split_pct/100
        costs = LabCosts(**meta["costs"])
        if meta["mode"].startswith("1s"):
            with connect() as db:
                rec = db.execute(
                    """SELECT quote_at,bid,ask FROM lsim_hyper_quotes_1s
                       WHERE provider_uic=? AND quote_at>=? AND quote_at<?
                       ORDER BY quote_at ASC LIMIT ?""",
                    (int(source.provider_instrument_id),
                     (measured_start-timedelta(seconds=45)).isoformat(),
                     measured_end.isoformat(), MAX_QUOTES+1)).fetchall()
            samples = tuple(dict(x) for x in rec)
            if len(samples) > MAX_QUOTES:
                raise ValueError("For mange 1s-priser for tidsdelt test.")
            evaluate = lambda a,b: replay_tick_impulses(
                plan=meta["plan"], quotes=samples, costs=costs,
                start_at=a,end_at=b)
        else:
            samples = CanonicalMarketBarStoreV2().load_instrument_range(
                instrument_id=int(source.instrument_id),
                start=measured_start-timedelta(hours=72),
                end=measured_end, limit=MAX_BARS+1)
            if len(samples) > MAX_BARS:
                raise ValueError("For mange 1m-priser for tidsdelt test.")
            evaluate = lambda a,b: replay_algorithm(
                plan=meta["plan"],bars=samples,costs=costs,
                start_at=a,end_at=b)
        train = evaluate(measured_start,split)
        test = evaluate(split,measured_end)
        st.session_state["alg:oos"] = (train,test,split,meta)
    except (ValueError, TypeError) as exc:
        st.error(str(exc))
    except Exception as exc:
        st.error("Out-of-sample-simulering feilet: " + type(exc).__name__)
if st.session_state.get("alg:oos"):
    train,test,split,meta = st.session_state["alg:oos"]
    c1,c2,c3,c4=st.columns(4)
    c1.metric("Train P/L", f"{train.pnl_nok:+,.2f} NOK")
    c2.metric("Train ret.", f"{train.return_pct:+.2f}%")
    c3.metric("Test P/L", f"{test.pnl_nok:+,.2f} NOK")
    c4.metric("Test ret.", f"{test.return_pct:+.2f}%")
    st.caption("Skillepunkt " + split.isoformat() +
               " UTC. To separate PAPER-porteføljer med lik startkapital. "
               "Ingen AI-adaptiv parameteroptimalisering er gjort her.")

st.subheader("5 · Eksperimenthistorikk i denne økten")
history = st.session_state.get("alg:experiment_history", [])
if history:
    history_rows = []
    for item in history:
        r = item["result"]
        m = item["metadata"]
        history_rows.append({
            "Kjørt (UTC)": item["at"], "Mal": item["label"],
            "UIC": m["uic"], "Periode fra": m["start"], "Periode til": m["end"],
            "Netto NOK": round(r.pnl_nok, 2),
            "Retur %": round(r.return_pct, 3),
            "Drawdown %": round(r.drawdown_pct, 3),
            "Ordre": len(r.trades), "Kostnader NOK": round(r.total_cost_nok, 2),
            "Plan": json.dumps(m["plan"], ensure_ascii=False, sort_keys=True),
        })
    st.dataframe(pd.DataFrame(history_rows), use_container_width=True, hide_index=True)
    st.download_button(
        "Eksporter eksperimentlogg (CSV)",
        pd.DataFrame(history_rows).to_csv(index=False).encode("utf-8"),
        file_name="algorithm_lab_experiments.csv", mime="text/csv",
        key="alg:download_history")
    current_meta = history[0]["metadata"]
    fingerprint = lambda m: (
        m["uic"], m["start"], m["end"], m.get("mode"),
        json.dumps(m["costs"], sort_keys=True))
    comparable = [x for x in history if fingerprint(x["metadata"]) ==
                  fingerprint(current_meta)]
    if len(comparable) >= 2:
        st.caption("Sammenlignbare kjøringer med identisk UIC, periode og "
                   "kostnadsforutsetninger. Bare algoritmeparametere varierer.")
        series = []
        for i, item in enumerate(reversed(comparable)):
            r = item["result"]
            start_nav = item["metadata"]["costs"]["starting_nav_nok"]
            series.append(pd.Series(
                {pt.at: 100*(pt.nav_nok/start_nav-1) for pt in r.points},
                name=f"Forsøk {i+1} · {item['label']}"))
        st.line_chart(pd.concat(series, axis=1).sort_index(), height=260)
    else:
        st.caption("Kjør samme UIC/periode/kostnadssett med en endret plan for "
                   "å sammenligne nettoprestasjon. Historikk er foreløpig "
                   "kun lagret i denne nettleserøkten.")

st.subheader("6 · Vedvarende modellversjoner")
st.caption("Eksperimenter lagres separat fra LIVE i PG-databasen. "
           "En lang forskningsnøkkel gir tilgang til dine eksperimenter. "
           "Lagre nøkkelen selv; den kan ikke gjenopprettes fra databasen.")
with st.expander("Forskningsnøkkel og lagrede forsøk", expanded=False):
    if st.button("Opprett ny hemmelig forskningsnøkkel", key="alg:newresearchkey"):
        token = new_research_key()
        st.session_state["alg:research_token_entry"] = token
        st.session_state["alg:last_new_research_key"] = token
    if st.session_state.get("alg:last_new_research_key"):
        st.code(st.session_state["alg:last_new_research_key"], language="text")
        st.warning("Kopier nøkkelen til et trygt sted før du forlater siden.")
    token = st.text_input(
        "Forskningsnøkkel (minimum 32 tegn)", type="password",
        key="alg:research_token_entry")
    lab_label = st.text_input("Navn på ny eksperimentversjon",
                              value=preset, key="alg:save_label")
    if st.button("Lagre siste simuleringsresultat", key="alg:save_experiment"):
        if saved is None:
            st.warning("Kjør en simulering først.")
        else:
            try:
                meta, result = saved
                context = {k: meta[k] for k in
                           ("market","uic","start","end","mode","costs")}
                report = {
                    "pnl_nok": result.pnl_nok,
                    "return_pct": result.return_pct,
                    "drawdown_pct": result.drawdown_pct,
                    "total_cost_nok": result.total_cost_nok,
                    "financing_nok": result.financing_nok,
                    "trades": len(result.trades), "gaps": result.gaps}
                saved_id = save_experiment(
                    token=token, label=lab_label,
                    plan=meta["plan"], context=context, results=report)
                st.success("Lagret PAPER-versjon: " + saved_id[:8])
            except (ValueError, TypeError) as exc:
                st.error(str(exc))
            except Exception as exc:
                st.error("Lagring er utilgjengelig: " + type(exc).__name__)
    if st.button("Hent mine tidligere eksperimenter", key="alg:list_experiments"):
        try:
            st.session_state["alg:server_experiments"] = list_experiments(
                token=token, limit=40)
        except (ValueError, TypeError) as exc:
            st.error(str(exc))
        except Exception as exc:
            st.error("Eksperimentarkiv utilgjengelig: " + type(exc).__name__)
    saved_list = st.session_state.get("alg:server_experiments", ())
    if saved_list:
        st.dataframe(pd.DataFrame([
            {"Opprettet": x["created_at"], "Navn": x["label"],
             "P/L NOK": x["results"].get("pnl_nok"),
             "Avkastning %": x["results"].get("return_pct"),
             "ID": x["experiment_id"]} for x in saved_list]),
             use_container_width=True, hide_index=True)
        selected = st.selectbox("Gjenåpne oppskrift",
                                saved_list, key="alg:stored_version",
                                format_func=lambda x: x["label"] + " · " +
                                x["experiment_id"][:8])
        if st.button("Åpne tidligere plan", key="alg:restore_version"):
            st.session_state["alg:pending_plan"] = selected["plan"]
            st.rerun()

st.subheader("7 · Datakatalog med tidsriktig kontekst")
st.caption("Eksplisitt kildevalg, punkt-i-tid-data og ingen vilkårlig SQL. "
           "Private Saxo-kontodata er ikke tilgjengelige for AI-koden.")
st.dataframe(pd.DataFrame(catalog_manifest()), use_container_width=True,
             hide_index=True)
context_kind = st.selectbox("Kontekstkilde", ("macro_schedule", "news_context"),
                            key="alg:context_source")
if st.button("Les kjent kontekst ved valgt sluttid", key="alg:context"):
    try:
        data = catalog_context(dataset=context_kind, as_of=end,
                               start=start, limit=100)
        st.session_state["alg:context_results"] = data
    except (ValueError, TypeError) as exc:
        st.error(str(exc))
context_data = st.session_state.get("alg:context_results")
if context_data is not None:
    st.caption("Dekning: " + context_data.coverage +
               " · tidsgrense " + context_data.as_of)
    st.dataframe(pd.DataFrame(context_data.rows), use_container_width=True,
                 hide_index=True)
    for note in context_data.limitations:
        st.caption(note)

st.subheader("8 · Rådata og siste registrerte BBO")
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
st.caption("Neste steg: isolert kode-sandbox uten Saxo-/DB-hemmeligheter, "
           "vedvarende modellversjoner og risiko-/finansieringsmodell. "
           "Sekund-replay bruker ekte historiske quotes og observerte spreads, "
           "men er ikke Saxo-ordrefyllinger.")
