from __future__ import annotations

import pandas as pd
import streamlit as st

from database import using_postgres
from signal_outcomes import SignalOutcomeStore, refresh_signal_outcomes

st.set_page_config(page_title="Signal History", page_icon="📈", layout="wide")
st.title("Signal History")

if using_postgres():
    st.caption("Live anbefalinger og prisutfall fra den delte PostgreSQL-databasen. Workeren oppdaterer resultatene kontinuerlig.")
    outcomes = SignalOutcomeStore().load_all()
else:
    st.caption("Anbefalinger måles mot pris ved signalet og etter én og fire timer. Lokalt fylles uferdige rader når siden åpnes.")
    with st.spinner("Oppdaterer prisresultater …"):
        outcomes = refresh_signal_outcomes()

if not outcomes:
    st.info("Ingen Market State-signaler er lagret ennå.")
    st.stop()

rows = []
for item in outcomes:
    directional_return_1h = None
    directional_return_4h = None
    if item.direction == "LONG":
        directional_return_1h = item.return_1h_pct
        directional_return_4h = item.return_4h_pct
    elif item.direction == "SHORT":
        if item.return_1h_pct is not None:
            directional_return_1h = -item.return_1h_pct
        if item.return_4h_pct is not None:
            directional_return_4h = -item.return_4h_pct

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
            "retningsresultat_1t_%": directional_return_1h,
            "retningsresultat_4t_%": directional_return_4h,
            "MFE_4t_%": item.mfe_4h_pct,
            "MAE_4t_%": item.mae_4h_pct,
            "prisleverandør": item.price_provider,
            "modell": item.model_version,
            "event_id": item.event_id,
        }
    )

frame = pd.DataFrame(rows)
completed_1h = frame[frame["avkastning_1t_%"].notna()]
completed_4h = frame[frame["avkastning_4t_%"].notna()]
directional_4h = frame[frame["retningsresultat_4t_%"].notna()]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Totale signaler", len(frame))
c2.metric("Ferdige 1t", len(completed_1h))
c3.metric("Ferdige 4t", len(completed_4h))
if not directional_4h.empty:
    hit_rate = (directional_4h["retningsresultat_4t_%"] > 0).mean() * 100
    c4.metric("Retningstreff 4t", f"{hit_rate:.1f} %", help=f"Kun LONG/SHORT, n={len(directional_4h)}")
else:
    c4.metric("Retningstreff 4t", "–", help="Ingen ferdige LONG/SHORT-signaler ennå")

st.dataframe(
    frame,
    use_container_width=True,
    hide_index=True,
    column_config={
        "score": st.column_config.NumberColumn(format="%+.3f"),
        "avkastning_1t_%": st.column_config.NumberColumn(format="%+.3f"),
        "avkastning_4t_%": st.column_config.NumberColumn(format="%+.3f"),
        "retningsresultat_1t_%": st.column_config.NumberColumn(format="%+.3f"),
        "retningsresultat_4t_%": st.column_config.NumberColumn(format="%+.3f"),
        "MFE_4t_%": st.column_config.NumberColumn(format="%+.3f"),
        "MAE_4t_%": st.column_config.NumberColumn(format="%+.3f"),
    },
)

st.download_button(
    "Last ned signalhistorikk som CSV",
    frame.to_csv(index=False).encode("utf-8"),
    file_name="pricegauger_signal_history.csv",
    mime="text/csv",
)
