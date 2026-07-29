from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from build_info import render_build_badge
from database import connect, using_postgres
from signal_outcomes import SignalOutcomeStore
from telegram_flow_store import TelegramFlowStore

LOCAL_TIMEZONE = ZoneInfo("Europe/Oslo")
CHANNEL_CODES = {
    "Middle_East_Spectator": "MES",
}


def _compact_timestamp(value: object) -> str:
    if value in (None, ""):
        return "–"
    parsed = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(parsed):
        return str(value)
    return parsed.tz_convert(LOCAL_TIMEZONE).strftime("%d.%m.%y · %H:%M")


def _channel_code(channel: str) -> str:
    cleaned = str(channel or "").strip().lstrip("@")
    if cleaned in CHANNEL_CODES:
        return CHANNEL_CODES[cleaned]
    words = [word for word in re.split(r"[^A-Za-z0-9]+", cleaned) if word]
    if len(words) >= 2:
        return "".join(word[0].upper() for word in words[:3])
    return (cleaned[:3] or "TG").upper()


def _compact_telegram_id(value: object) -> str:
    raw = str(value or "").strip()
    match = re.fullmatch(r"telegram:([^:]+):(\d+)", raw, flags=re.IGNORECASE)
    if not match:
        return raw or "–"
    channel, message_number = match.groups()
    return f"{_channel_code(channel)}:{message_number}"


st.set_page_config(page_title="Worker Status", page_icon="🟢", layout="wide")
render_build_badge()
st.title("PriceGauger Worker Status")
st.caption("Read-only produksjonsstatus fra workeren og den delte databasen.")

if not using_postgres():
    st.warning(
        "Denne visningen leser lokal SQLite, ikke den delte Railway-databasen. "
        "Legg DATABASE_URL i Streamlit-miljøet for å vise faktisk worker-status."
    )

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
flow_snapshot = TelegramFlowStore().load_latest_snapshot()
completed_1h = [item for item in outcomes if item.return_1h_pct is not None]
completed_4h = [item for item in outcomes if item.return_4h_pct is not None]
latest_worker = worker_rows[0]["recorded_at"] if worker_rows else None

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Lagrede signaler", len(outcomes))
c2.metric("Ferdige 1t", len(completed_1h))
c3.metric("Ferdige 4t", len(completed_4h))
c4.metric("Siste worker-hendelse", _compact_timestamp(latest_worker))
c5.metric("Siste Telegram Flow", _compact_timestamp(flow_snapshot.as_of if flow_snapshot else None))

if flow_snapshot:
    st.subheader("Telegram Flow-status")
    st.caption(
        f"{flow_snapshot.post_count} scorede poster · {flow_snapshot.event_cluster_count} hendelsesklynger · "
        f"modell {flow_snapshot.model or 'ukjent'}"
    )
    flow_rows = [
        {
            "marked": item.asset,
            "retning": item.direction,
            "flow-score": item.flow_score,
            "confidence": item.confidence,
            "aktive hendelser": item.selected_event_count,
        }
        for item in flow_snapshot.assets
    ]
    st.dataframe(pd.DataFrame(flow_rows), use_container_width=True, hide_index=True)

if latest_interpretation:
    payload = json.loads(latest_interpretation["payload_json"])
    st.subheader("Siste tolket hendelse")
    st.write(f"**{_compact_telegram_id(latest_interpretation['event_id'])}**")
    st.caption(
        f"Publisert {_compact_timestamp(latest_interpretation['published_at'])} · "
        f"type {latest_interpretation['update_type']}"
    )
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
    st.caption(f"Oppdatert {_compact_timestamp(latest_snapshot['as_of'])}")
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
    st.caption(f"Beregnet {_compact_timestamp(latest_as_of)}")
    st.dataframe(pd.DataFrame(recommendation_rows), use_container_width=True, hide_index=True)

st.subheader("Siste worker-registreringer")
if worker_rows:
    worker_display = []
    for row in worker_rows:
        worker_display.append(
            {
                "melding": _compact_telegram_id(row["message_id"]),
                "status": row["status"],
                "tid": _compact_timestamp(row["recorded_at"]),
            }
        )
    st.dataframe(pd.DataFrame(worker_display), use_container_width=True, hide_index=True)
else:
    st.info("Ingen worker-registreringer funnet.")

st.caption(
    f"Siden lest {_compact_timestamp(datetime.now(timezone.utc))} · "
    f"backend={'PostgreSQL' if using_postgres() else 'SQLite'}"
)
