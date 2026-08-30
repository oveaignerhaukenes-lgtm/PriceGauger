from __future__ import annotations

import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from build_info import render_build_badge
from context_snapshot_store_v2 import ContextSnapshotStoreV2
from database import connect, database_config_status, using_postgres
from realtime_market_data import RealtimeMarketDataStore
from runtime_health_v2 import load_runtime_health_v2
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


def _refresh_label(value: int | None) -> str:
    if value is None:
        return "Ukjent"
    if value < 1000:
        return f"{value} ms"
    return f"{value / 1000.0:g} s"


def _delay_label(value: float | None) -> str:
    if value is None:
        return "Ukjent"
    if value <= 0:
        return "Realtime"
    return f"{value:g} min forsinket"


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
st.caption("Read-only produksjonsstatus for aktive source-, Context-v2- og Technical-v2-runtimer.")

db_status = database_config_status()
if not using_postgres():
    st.warning(
        "DATABASE_URL eller DATABASE_PUBLIC_URL ble ikke funnet i denne Streamlit-appen. "
        f"Konfigurasjonsstatus: {db_status['source']}."
    )
    st.info(
        "Worker Status krever delt PostgreSQL. Lokal SQLite er bare test/lokal kompatibilitet og brukes ikke "
        "som produksjonsautoritet."
    )
    st.stop()

st.success(f"Delt PostgreSQL er aktiv via {db_status['source']}.")

with connect() as db:
    worker_rows = db.execute(
        "SELECT message_id, status, recorded_at FROM worker_messages ORDER BY recorded_at DESC LIMIT 10"
    ).fetchall()
    flow_post_status = db.execute(
        "SELECT COUNT(*) AS count, MAX(scored_at) AS latest FROM telegram_flow_posts"
    ).fetchone()
    flow_snapshot_status = db.execute(
        "SELECT COUNT(*) AS count, MAX(recorded_at) AS latest FROM telegram_flow_snapshots"
    ).fetchone()

flow_snapshot = TelegramFlowStore().load_latest_snapshot()
context_snapshot = ContextSnapshotStoreV2().load_latest(scope_key="global")
try:
    runtime_health = load_runtime_health_v2()
except Exception:
    runtime_health = ()

latest_worker = worker_rows[0]["recorded_at"] if worker_rows else None
flow_post_count = int(flow_post_status["count"] or 0)
flow_snapshot_count = int(flow_snapshot_status["count"] or 0)
healthy_count = sum(1 for item in runtime_health if item.status == "HEALTHY")

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Telegram-poster", flow_post_count)
c2.metric("Flow-snapshots", flow_snapshot_count)
c3.metric("Context v2", _compact_timestamp(context_snapshot.as_of if context_snapshot else None))
c4.metric("V2 health", f"{healthy_count}/{len(runtime_health)}")
c5.metric("Siste worker-hendelse", _compact_timestamp(latest_worker))

st.subheader("Canonical v2 runtime-health")
if runtime_health:
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "service": item.service,
                    "stage": item.stage,
                    "status": item.status,
                    "detail": item.detail,
                }
                for item in runtime_health
            ]
        ),
        width="stretch",
        hide_index=True,
    )
else:
    st.info("Ingen pg_v2_runtime_status-rader er lagret ennå.")

st.subheader("Saxo realtime-stream")
realtime_store = RealtimeMarketDataStore()
stream_statuses = realtime_store.load_statuses()
if stream_statuses:
    stream_rows = []
    for status in stream_statuses:
        latest_bar = realtime_store.load_latest_bar(market=status.market)
        stream_rows.append(
            {
                "marked": status.market,
                "stream": status.state,
                "tildelt refresh": _refresh_label(status.actual_refresh_ms),
                "ønsket refresh": _refresh_label(status.requested_refresh_ms),
                "delay": _delay_label(status.delay_minutes),
                "siste quote": _compact_timestamp(status.last_quote_at),
                "siste 1m-bar": _compact_timestamp(latest_bar.bar_time if latest_bar else None),
                "kontrakt": latest_bar.symbol if latest_bar and latest_bar.symbol else "–",
            }
        )
    st.dataframe(pd.DataFrame(stream_rows), width="stretch", hide_index=True)
else:
    st.info("Ingen Saxo realtime-streamstatus er lagret ennå.")

st.subheader("Telegram Flow source-status")
if flow_snapshot:
    st.caption(
        f"{flow_snapshot.post_count} scorede poster · {flow_snapshot.event_cluster_count} hendelsesklynger · "
        f"modell {flow_snapshot.model or 'ukjent'} · as_of {_compact_timestamp(flow_snapshot.as_of)}"
    )
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "marked": item.asset,
                    "retning": item.direction,
                    "flow-score": item.flow_score,
                    "confidence": item.confidence,
                    "aktive hendelser": item.selected_event_count,
                }
                for item in flow_snapshot.assets
            ]
        ),
        width="stretch",
        hide_index=True,
    )
else:
    d1, d2, d3, d4 = st.columns(4)
    d1.metric("Scorede poster", flow_post_count)
    d2.metric("Lagrede snapshots", flow_snapshot_count)
    d3.metric("Siste postscore", _compact_timestamp(flow_post_status["latest"]))
    d4.metric("Siste snapshot", _compact_timestamp(flow_snapshot_status["latest"]))

st.subheader("Canonical ContextSnapshotV2")
if context_snapshot is None:
    st.warning("Ingen canonical ContextSnapshotV2 er publisert ennå.")
else:
    st.caption(
        f"snapshot {context_snapshot.snapshot_id} · as_of {_compact_timestamp(context_snapshot.as_of)} · "
        f"freshness {context_snapshot.freshness_status} · engine {context_snapshot.engine_version}"
    )
    if context_snapshot.regime_label:
        st.markdown(f"**{context_snapshot.regime_label}**")
    if context_snapshot.summary:
        st.write(context_snapshot.summary)
    if context_snapshot.targets:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "marked": target.target_key,
                        "konteksttrykk": target.directional_bias,
                        "confidence": target.confidence,
                        "novelty": target.novelty,
                        "event risk": target.event_risk,
                    }
                    for target in context_snapshot.targets
                ]
            ),
            width="stretch",
            hide_index=True,
        )

st.subheader("Siste worker-registreringer")
if worker_rows:
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "melding": _compact_telegram_id(row["message_id"]),
                    "status": row["status"],
                    "tid": _compact_timestamp(row["recorded_at"]),
                }
                for row in worker_rows
            ]
        ),
        width="stretch",
        hide_index=True,
    )
else:
    st.info("Ingen worker-registreringer funnet.")

st.caption(
    f"Siden lest {_compact_timestamp(datetime.now(timezone.utc))} · "
    f"backend=PostgreSQL · config={db_status['source']}"
)
