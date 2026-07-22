from __future__ import annotations

import pandas as pd
import streamlit as st

from signal_outcomes import SignalOutcomeStore, refresh_signal_outcomes

st.set_page_config(page_title="Signal History", page_icon="📈", layout="wide")
st.title("Signal History")
st.caption("Anbefalinger måles mot pris ved signalet og etter én og fire timer. Uferdige rader fylles når siden åpnes.")

with st.spinner("Oppdaterer prisresultater …"):
    outcomes = refresh_signal_outcomes()

if not outcomes:
    st.info("Ingen Market State-signaler er lagret ennå.")
    st.stop()

rows = []
for item in outcomes:
    directional_return_4h = item.return_4h_pct
    if directional_return_4h is not None and item.direction == "SHORT":
        directional_return_4h = -directional_return_4h
    rows.append(
        {
            "tid": item.created_at,
            "marked": item.asset,
            "retning": item.direction,
            "styrke": item.signal_strength,
            "score": item.score,
            "pris_signal": item.price_at_signal,
            "pris_1t": item.price_1h,
            "pris_4t": item.price_4h,
            "avkastning_1t_%": item.return_1h_pct,
            "avkastning_4t_%": item.return_4h_pct,
            "retningsresultat_4t_%": directional_return_4h,
            "MFE_4t_%": item.mfe_4h_pct,
            "MAE_4t_%": item.mae_4h_pct,
            "modell": item.model_version,
            "event_id": item.event_id,
        }
    )

frame = pd.DataFrame(rows)
completed = frame[frame["retningsresultat_4t_%"].notna()]
if not completed.empty:
    c1, c2, c3 = st.columns(3)
    c1.metric("Ferdige 4t-signaler", len(completed))
    c2.metric("Retningstreff", f"{(completed['retningsresultat_4t_%'] > 0).mean() * 100:.1f} %")
    c3.metric("Gjennomsnittlig retningsresultat", f"{completed['retningsresultat_4t_%'].mean():+.3f} %")

st.dataframe(
    frame,
    use_container_width=True,
    hide_index=True,
    column_config={
        "score": st.column_config.NumberColumn(format="%+.3f"),
        "avkastning_1t_%": st.column_config.NumberColumn(format="%+.3f"),
        "avkastning_4t_%": st.column_config.NumberColumn(format="%+.3f"),
        "retningsresultat_4t_%": st.column_config.NumberColumn(format="%+.3f"),
        "MFE_4t_%": st.column_config.NumberColumn(format="%+.3f"),
        "MAE_4t_%": st.column_config.NumberColumn(format="%+.3f"),
    },
)
