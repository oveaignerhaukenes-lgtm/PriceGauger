from __future__ import annotations

import pandas as pd
import streamlit as st

from event_resolution import canonical_event_from_plan
from market_state_service import process_market_event


def render_market_state_panel(plan) -> None:
    st.markdown("### Market State · testmotor")
    st.caption(
        "Denne versjonen bruker en deterministisk mock-tolk. Den tester hele flyten og loggingen, "
        "men er ennå ikke en ekte AI-vurdering."
    )
    try:
        result = process_market_event(canonical_event_from_plan(plan))
    except Exception as exc:
        st.error(f"Market State kunne ikke beregnes: {exc}")
        return

    if result.created:
        st.success("Ny Telegram-observasjon tolket og lagret.")
    else:
        st.info("Observasjonen var allerede lagret; state og anbefalinger er beregnet på nytt.")

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

    state_rows = [
        {
            "tilstand": name,
            "nivå": value,
            "endring_1t": result.state.change_1h[name],
            "endring_4t": result.state.change_4h[name],
        }
        for name, value in result.state.values.items()
    ]
    with st.expander("Se state-vektor og drivere"):
        st.dataframe(pd.DataFrame(state_rows), use_container_width=True, hide_index=True)
        st.markdown("**Tolkning**")
        st.write(result.interpretation.summary)
        st.caption(
            f"{result.interpretation.model_version} · {result.interpretation.prompt_version} · "
            f"{result.interpretation.update_type}"
        )
        for recommendation in recommendations:
            if recommendation.rationale:
                st.write(f"**{recommendation.asset}:** " + " · ".join(recommendation.rationale))
