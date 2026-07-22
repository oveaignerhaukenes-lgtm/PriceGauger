from __future__ import annotations

import pandas as pd
import streamlit as st

from config import openai_api_key, openai_market_model
from event_resolution import canonical_event_from_plan
from market_interpreter import MockMarketInterpreter, StructuredMarketInterpreter
from market_state_service import process_market_event
from openai_market_provider import OpenAIJsonProvider


def _interpreter_choice():
    key = openai_api_key()
    options = ["Mock"] + (["OpenAI"] if key else [])
    default_index = 1 if key else 0
    selected = st.selectbox(
        "Tolkingsmotor",
        options,
        index=default_index,
        help="OpenAI bruker strengt JSON-schema. Mock er deterministisk og krever ingen nøkkel.",
    )
    if selected == "OpenAI":
        model = openai_market_model()
        return StructuredMarketInterpreter(OpenAIJsonProvider(api_key=key, model_version=model)), model
    return MockMarketInterpreter(), "mock-interpreter-v1"


def render_market_state_panel(plan) -> None:
    st.markdown("### Market State")
    interpreter, model_name = _interpreter_choice()
    if model_name.startswith("mock"):
        st.caption(
            "Testmodus: deterministisk mock-tolk. Flyt og logging er reell, men dette er ikke en AI-vurdering."
        )
    else:
        st.caption(
            f"Strukturert AI-tolkning med {model_name}. Modellen leverer state-deltaer, ikke handelsbeslutningen."
        )

    force = st.button("Tolk siste hendelse på nytt", help="Overskriver lagret tolkning for denne Telegram-hendelsen.")
    try:
        result = process_market_event(
            canonical_event_from_plan(plan),
            interpreter=interpreter,
            force_reinterpret=force,
        )
    except Exception as exc:
        st.error(f"Market State kunne ikke beregnes: {exc}")
        return

    recommendations = list(result.recommendations)
    columns = st.columns(len(recommendations))
    for column, recommendation in zip(columns, recommendations):
        with column:
            st.metric(
                recommendation.asset,
                recommendation.direction,
                delta=f"styrke {recommendation.signal_strength}/100",
            )
            st.caption(f"Score {recommendation.score:+.3f} · {recommendation.horizon_hours} t")

    st.caption(
        f"Lagret modell: {result.interpretation.model_version} · prompt: "
        f"{result.interpretation.prompt_version} · schema: {result.interpretation.schema_version} · "
        f"type: {result.interpretation.update_type}"
    )
    state_rows = [
        {
            "tilstand": name,
            "nivå": value,
            "endring_1t": result.state.change_1h[name],
            "endring_4t": result.state.change_4h[name],
        }
        for name, value in result.state.values.items()
    ]
    with st.expander("Se state-vektor, evidens og drivere"):
        st.dataframe(pd.DataFrame(state_rows), use_container_width=True, hide_index=True)
        st.markdown("**Tolkning**")
        st.write(result.interpretation.summary)
        if result.interpretation.evidence:
            st.markdown("**Tekstgrunnlag**")
            for item in result.interpretation.evidence:
                st.write(f"- {item}")
        if result.interpretation.uncertainties:
            st.markdown("**Usikkerhet**")
            for item in result.interpretation.uncertainties:
                st.write(f"- {item}")
        for recommendation in recommendations:
            if recommendation.rationale:
                st.write(f"**{recommendation.asset}:** " + " · ".join(recommendation.rationale))
