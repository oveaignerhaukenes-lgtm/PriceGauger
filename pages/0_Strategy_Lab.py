from __future__ import annotations
import streamlit as st
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
