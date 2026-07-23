from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from database import connect, using_postgres
from signal_outcomes import SignalOutcomeStore

st.set_page_config(page_title="Live Status", page_icon="🟢", layout="wide")
st.title("PriceGauger Live")
st.caption("Read-only produksjonsstatus fra den delte databasen.")

if not using_postgres():
    st.warning("Denne siden bruker lokal SQLite. Legg inn DATABASE_URL for å vise Railway-data.")

with connect() as db:
    worker_rows = db.execute(
        "SELECT message_id, status, recorded_at FROM worker_messages ORDER BY recorded_at DESC LIMIT 10"
    ).fetchall()
    latest_interpretation = db.execute(
        "SELECT event_id, published_at, update_type, payload_json FROM market_interpretations ORDER BY published_at DESC LIMIT 1"
    ).fetchone()
    latest_snapshot = db.execute(
        "SELECT as_of, payload_json FROM market_state_snapshots ORDER BY as_of DESC LIMIT 1"
    ).fetchone()
    recommendations = db.execute(
        "SELECT as_of, asset, payload_json FROM asset_recommendations ORDER BY as_of DESC"
    ).fetchall()

outcomes = SignalOutcomeStore().load_all()
completed_1h = [item for item in outcomes if item.return_1h_pct is not None]
completed_4h = [item for item in outcomes if item.return_4h_pct is not None]
processed = [row for row in worker_rows if row["status"] == "processed"]
latest_worker = worker_rows[0]["recorded_at"] if worker_rows else None

c1, c2, c3, c4 = st.columns(4)
c1.metric("Lagrede signaler", len(outcomes))
c2.metric("Ferdige 1t", len(completed_1h))
c3.metric("Ferdige 4t", len(completed_4h))
c4.metric("Siste worker-hendelse", latest_worker or "–")

if latest_interpretation:
    payload = json.loads(latest_interpretation["payload_json"])
    st.subheader("Siste tolket hendelse")
    st.write(f"**{latest_interpretation['event_id']}**")
    st.caption(f"Publisert {latest_interpretation['published_at']} · type {latest_interpretation['update_type']}")
    summary = payload.get("summary") or payload.get("event_summary") or payload.get("reasoning_summary")
    if summary:
        st.write(summary)
    with st.expander("Strukturert tolkning"):
        st.json(payload)
else:
    st.info("Ingen tolkede hendelser er lagret ennå.")

if latest_snapshot:
    snapshot = json.loads(latest_snapshot["payload_json"])
    st.subheader("Gjeldende Market State")
    st.caption(f"Oppdatert {latest_snapshot['as_of']}")
    numeric = {
        key: value
        for key, value in snapshot.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }
    if numeric:
        cols = st.columns(min(4, len(numeric)))
        for index, (key, value) in enumerate(numeric.items()):
            cols[index % len(cols)].metric(key.replace("_", " ").title(), f"{value:.2f}")
    with st.expander("Hele Market State"):
        st.json(snapshot)

if recommendations:
    latest_as_of = recommendations[0]["as_of"]
    latest = [row for row in recommendations if row["as_of"] == latest_as_of]
    recommendation_rows = []
    for row in latest:
        payload = json.loads(row["payload_json"])
        recommendation_rows.append(
            {
                "marked": row["asset"],
                "retning": payload.get("direction"),
                "styrke": payload.get("signal_strength"),
                "score": payload.get("score"),
                "begrunnelse": payload.get("rationale") or payload.get("reason"),
            }
        )
    st.subheader("Siste anbefalinger")
    st.caption(f"Beregnet {latest_as_of}")
    st.dataframe(pd.DataFrame(recommendation_rows), use_container_width=True, hide_index=True)

st.subheader("Siste worker-registreringer")
if worker_rows:
    st.dataframe(pd.DataFrame([dict(row) for row in worker_rows]), use_container_width=True, hide_index=True)
else:
    st.info("Ingen worker-registreringer funnet.")

st.caption(f"Siden lest {datetime.now(timezone.utc).isoformat()} · backend={'PostgreSQL' if using_postgres() else 'SQLite'}")
