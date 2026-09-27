from __future__ import annotations
import streamlit as st
from uuid import uuid4
from config import openai_api_key
from strategy_discussion_ai_v1 import answer_strategy_discussion_v1
from strategy_discussion_store_v1 import append_strategy_message_v1, load_strategy_messages_v1
from research_trade_plan_store_v1 import create_research_trade_plan_v1, load_research_trade_plans_v1
from research_strategy_store_v1 import (
    STRATEGY_KEY_GOLD_FED, append_research_event_v1,
    load_research_events_v1, seed_gold_fed_hypothesis_v1,
)

st.title("Strategy Lab")
st.caption("Levende strategier med eksplisitte hypoteser, scenarioer og falsifikasjon.")
seed_gold_fed_hypothesis_v1()

strategy = st.query_params.get("strategy")
if isinstance(strategy, list):
    strategy = strategy[0] if strategy else None

if strategy != STRATEGY_KEY_GOLD_FED:
    st.subheader("Strategier")
    st.markdown("**Gull + Fed/renter** · research · 1–3 uker · v1")
    st.caption("Fed-transmisjon → realrenter/USD → mulig regimeskifte når økonomisk stress møter vedvarende inflasjon.")
    if st.button("Åpne Gull + Fed/renter", type="primary", use_container_width=True):
        st.query_params["strategy"] = STRATEGY_KEY_GOLD_FED
        st.rerun()
    st.info("Eksisterende AutoTrader-strategier fortsetter i sine nåværende simulator- og execution-flater. Denne siden introduserer research-strategier uten execution authority.")
    st.stop()

if st.button("← Alle strategier"):
    st.query_params.clear()
    st.rerun()

st.header("Gull + Fed/renter")
st.caption("Research strategy · ingen execution authority")
events = load_research_events_v1(STRATEGY_KEY_GOLD_FED)
latest_version = max((event.version for event in events), default=1)

left, right = st.columns([2, 1])
with left:
    st.subheader("Arbeidshypotese")
    hypothesis = next((event for event in reversed(events) if event.event_type == "hypothesis"), None)
    if hypothesis:
        st.markdown(hypothesis.body)
with right:
    st.metric("Hypoteseversjon", f"v{latest_version}")
    supporting = sum(event.verdict == "supports" for event in events)
    contradicting = sum(event.verdict == "contradicts" for event in events)
    st.caption(f"Evidence journal: {supporting} støtter · {contradicting} motsier")

st.subheader("Scenario-modell")
scenarios = (
    ("A · Fed vinner narrativet", "2Y ↑ · real 10Y ↑ · DXY ↑ · gull ↓", "Motvind"),
    ("B · Transmisjon", "Aktivitet/kreditt svekkes · 2Y flater · gull slutter å lage nye lows", "Overgang"),
    ("C · Markedet tviler", "Inflasjon sticky · 2Y ↓ · DXY ↓ · lange yields høye · gull bryter opp", "Medvind"),
    ("D · Policyrespons", "Fed må lette før inflasjonen er slått ned", "Sterk asymmetri"),
)
for name, signals, implication in scenarios:
    with st.expander(f"{name} — {implication}", expanded=name.startswith("A")):
        st.write(signals)

st.subheader("Nøkkelsignaler")
st.caption("2Y · 10Y · 10Y real/TIPS · breakeven · DXY · Brent · gull · sølv")
st.caption("Modellen skal senere hente disse automatisk. Første versjon holder observasjon og tolkning eksplisitt adskilt, slik at hypotesen ikke omskrives i ettertid.")

st.subheader("Hypotesetidslinje")
for event in reversed(events):
    verdict = {"baseline":"BASELINE","supports":"STØTTER","contradicts":"MOTSIER","neutral":"NØYTRAL","revision":"REVISJON"}.get(event.verdict, event.verdict.upper())
    st.markdown(f"**{event.observed_at:%Y-%m-%d %H:%M} UTC · v{event.version} · {verdict}**  \n{event.title}  \n{event.body}")

with st.expander("Legg til evidens / falsifikasjon"):
    with st.form("gold-fed-evidence"):
        verdict = st.selectbox("Vurdering", ("supports", "contradicts", "neutral"))
        title = st.text_input("Kort tittel")
        body = st.text_area("Observasjon og begrunnelse")
        submitted = st.form_submit_button("Legg til i tidslinjen")
        if submitted:
            if not title.strip() or not body.strip():
                st.error("Tittel og observasjon må fylles ut.")
            else:
                append_research_event_v1(strategy_key=STRATEGY_KEY_GOLD_FED, version=latest_version,
                    event_type="evidence", verdict=verdict, title=title, body=body)
                st.rerun()

with st.expander("Revider hypotesen → ny versjon"):
    st.warning("Revisjon oppretter en ny, datert hypoteseversjon. Tidligere versjoner beholdes uendret i tidslinjen.")
    with st.form("gold-fed-revision"):
        title = st.text_input("Revisjonstittel", value=f"Hypotese v{latest_version + 1}")
        body = st.text_area("Ny arbeidshypotese")
        submitted = st.form_submit_button("Opprett ny versjon")
        if submitted:
            if not body.strip():
                st.error("Ny hypotese kan ikke være tom.")
            else:
                append_research_event_v1(strategy_key=STRATEGY_KEY_GOLD_FED, version=latest_version + 1,
                    event_type="hypothesis", verdict="revision", title=title, body=body)
                st.rerun()


st.divider()
st.subheader("Trade Plan")
st.caption("Planen er deterministisk og research-only. Den sender ingen ordre til Saxo eller AutoTrader.")

plans = load_research_trade_plans_v1(STRATEGY_KEY_GOLD_FED)
with st.expander("Ny Trade Plan", expanded=not bool(plans)):
    with st.form("gold-fed-trade-plan"):
        instrument_label = st.text_input("Instrument", value="Gold")
        direction = st.selectbox("Retning", ("LONG", "SHORT"))
        probability_pct = st.slider("Hypotesesannsynlighet (%)", 1, 99, 60)
        capital_pct = st.number_input("Tillatt strategikapital (%)", min_value=0.1, max_value=100.0, value=20.0, step=1.0)
        stop_loss_pct = st.number_input("Hard stop-loss (%)", min_value=0.1, value=5.0, step=0.5)
        trail_activation_pct = st.number_input("Aktiver trailing etter gevinst (%)", min_value=0.1, value=2.0, step=0.5)
        trailing_distance_pct = st.number_input("Trailing-avstand (%)", min_value=0.1, value=1.0, step=0.25)
        event_policy = st.selectbox("Makro-event policy", (
            "MANUAL_REVIEW",
            "FLAT_BEFORE_HIGH_RISK",
            "REDUCE_BEFORE_HIGH_RISK",
            "KEEP",
        ))
        rationale = st.text_area("Begrunnelse / entry-betingelser")
        submitted = st.form_submit_button("Opprett DRAFT-plan")
        if submitted:
            create_research_trade_plan_v1(
                strategy_key=STRATEGY_KEY_GOLD_FED,
                hypothesis_version=latest_version,
                instrument_label=instrument_label,
                direction=direction,
                probability_pct=probability_pct,
                capital_pct=capital_pct,
                stop_loss_pct=stop_loss_pct,
                trail_activation_pct=trail_activation_pct,
                trailing_distance_pct=trailing_distance_pct,
                event_policy=event_policy,
                rationale=rationale,
            )
            st.rerun()

if plans:
    st.markdown("**Ordrebok / planer**")
    for plan in plans:
        st.markdown(
            f"**{plan.status} · {plan.instrument_label} {plan.direction} · "
            f"P={plan.probability_pct:.0f}% · v{plan.hypothesis_version}**  \\n"
            f"Kapital {plan.capital_pct:g}% · SL {plan.stop_loss_pct:g}% · "
            f"trail fra +{plan.trail_activation_pct:g}% / avstand {plan.trailing_distance_pct:g}% · "
            f"event: {plan.event_policy}"
        )
        if plan.rationale:
            st.caption(plan.rationale)

st.info("Neste execution-steg blir en eksplisitt godkjenning som oversetter en DRAFT-plan til den eksisterende durable execution-livssyklusen. Denne versjonen kan ikke handle.")


st.divider()
st.subheader("Strategidiskusjon")
st.caption("Delt PG-minne: samtalen lagres per strategi og følger strategien mellom sesjoner.")

discussion = list(load_strategy_messages_v1(STRATEGY_KEY_GOLD_FED))
for message in discussion:
    with st.chat_message(str(message["role"])):
        st.markdown(str(message["content"]))

if not openai_api_key():
    st.info("OPENAI_API_KEY mangler; strategidiskusjon er ikke tilgjengelig ennå.")
else:
    prompt = st.chat_input("Diskuter, kritiser eller korriger strategien …", key="gold-fed-strategy-chat")
    if prompt:
        append_strategy_message_v1(
            message_id=str(uuid4()), strategy_key=STRATEGY_KEY_GOLD_FED, role="user",
            content=str(prompt), hypothesis_version=latest_version,
        )
        messages=list(load_strategy_messages_v1(STRATEGY_KEY_GOLD_FED))
        with st.chat_message("assistant"):
            with st.spinner("Leser hypotesetidslinje, Trade Plans og tidligere diskusjon …"):
                try:
                    answer=answer_strategy_discussion_v1(STRATEGY_KEY_GOLD_FED, messages)
                except Exception as exc:
                    st.error(f"Strategidiskusjon kunne ikke svare: {exc}")
                    st.stop()
            st.markdown(answer)
        append_strategy_message_v1(
            message_id=str(uuid4()), strategy_key=STRATEGY_KEY_GOLD_FED, role="assistant",
            content=answer, hypothesis_version=latest_version,
        )
        st.rerun()
