from __future__ import annotations

import streamlit as st

from autotrader_runtime_watchdog_v1 import (
    format_watchdog_report_v1,
    load_watchdog_findings_v1,
    load_watchdog_report_by_id_v1,
    load_watchdog_reports_v1,
    load_watchdog_status_v1,
)
from build_info import render_build_badge
from runtime_diagnostics import build_runtime_diagnostic_report


st.set_page_config(page_title="Runtime Diagnostics · PriceGauger", page_icon="🧭", layout="wide")
render_build_badge()
st.title("Runtime Diagnostics")
st.caption(
    "Read-only kontroll av persistens, markedsdata og AutoTrader-kjeden fra signal til faktisk Saxo-eksponering."
)

report = build_runtime_diagnostic_report()

col1, col2, col3 = st.columns(3)
col1.metric("Backend", report.backend)
col2.metric("Konfigurasjonskilde", report.source)
col3.metric("Runtime", report.runtime)
st.code(report.database_fingerprint, language=None)
st.caption("Fingeravtrykket inneholder ikke brukernavn, passord eller full database-URL.")

st.subheader("Persistente tabeller")
rows = [
    {
        "tabell": item.table,
        "status": item.status,
        "rader": item.count,
        "siste tidspunkt": item.latest,
        "feil": item.error,
    }
    for item in report.tables
]
st.dataframe(rows, use_container_width=True, hide_index=True)

st.subheader("Decision State-markeder")
if report.decision_markets:
    st.write(", ".join(report.decision_markets))
else:
    st.warning("Ingen Decision State-markeder ble funnet.")

st.subheader("Automatisk diagnose")
for message in report.diagnosis:
    if "complete" in message.lower():
        st.success(message)
    else:
        st.warning(message)

st.info(
    "Denne siden analyserer bare databasen som Streamlit faktisk er koblet til. "
    "Den skriver eller reparerer ingenting."
)


st.divider()
st.subheader("AutoTrader runtime watchdog")
st.caption(
    "Flight recorder uten execution-authority. Watchdog-en sammenligner uavhengig MACD-cross, "
    "strategiens target/pending state, execution-lifecycle og faktisk Saxo-nettoposisjon."
)

try:
    watchdog_status = load_watchdog_status_v1()
    watchdog_reports = load_watchdog_reports_v1(limit=80)
    watchdog_findings = load_watchdog_findings_v1(limit=100, include_resolved=True)
except Exception as exc:
    watchdog_status = None
    watchdog_reports = ()
    watchdog_findings = ()
    st.info(f"Watchdog-tabellene er ikke tilgjengelige ennå: {type(exc).__name__}: {exc}")

if watchdog_status is not None:
    checked_at = watchdog_status.get("checked_at")
    status_cols = st.columns(4)
    status_cols[0].metric("Siste kontroll", str(checked_at or "—"))
    status_cols[1].metric("Piloter kontrollert", int(watchdog_status.get("evaluated") or 0))
    status_cols[2].metric("Åpne funn", int(watchdog_status.get("open_findings") or 0))
    status_cols[3].metric("Feilede kontroller", int(watchdog_status.get("failed") or 0))
    detail = str(watchdog_status.get("detail") or "")
    if int(watchdog_status.get("failed") or 0) > 0:
        st.warning(detail)
    else:
        st.caption(detail or "Watchdog kjører.")

open_findings = [item for item in watchdog_findings if item.get("resolved_at") is None]
if open_findings:
    st.warning(f"{len(open_findings)} aktiv(e) watchdog-funn.")
    st.dataframe(
        [
            {
                "severity": item.get("severity"),
                "code": item.get("code"),
                "pilot": item.get("pilot_key"),
                "summary": item.get("summary"),
                "opened": item.get("opened_at"),
                "last_seen": item.get("last_seen_at"),
                "count": item.get("occurrence_count"),
            }
            for item in open_findings
        ],
        use_container_width=True,
        hide_index=True,
    )
elif watchdog_status is not None:
    st.success("Ingen aktive signal/target/execution/position-avvik registrert.")

requested_report_id = str(st.query_params.get("watchdog_report", "") or "").strip()
selected_report = load_watchdog_report_by_id_v1(requested_report_id) if requested_report_id else None
if selected_report is None and watchdog_reports:
    selected_report = watchdog_reports[0]

if selected_report is not None:
    if requested_report_id != selected_report.report_id:
        st.query_params["watchdog_report"] = selected_report.report_id
    st.markdown("#### Delbar watchdog-rapport")
    st.caption(
        "URL-en til denne siden inneholder rapport-ID-en. Du kan sende hele URL-en eller bare rapport-ID-en; "
        "rapportteksten under er også laget for å kopieres direkte inn i en chat."
    )
    st.code(format_watchdog_report_v1(selected_report), language=None)

if watchdog_reports:
    st.markdown("#### Nylige rapporter")
    st.dataframe(
        [
            {
                "report_id": item.report_id,
                "checked_at": item.checked_at,
                "market": item.market_name,
                "strategy": item.strategy_key,
                "desired": item.desired_direction,
                "observed": item.observed_direction,
                "cross": item.authoritative_cross_direction,
                "cross_ack": item.authoritative_cross_acknowledged,
                "findings": len(item.findings),
            }
            for item in watchdog_reports[:30]
        ],
        use_container_width=True,
        hide_index=True,
    )

resolved_findings = [item for item in watchdog_findings if item.get("resolved_at") is not None]
if resolved_findings:
    with st.expander("Nylig løste watchdog-funn"):
        st.dataframe(
            [
                {
                    "severity": item.get("severity"),
                    "code": item.get("code"),
                    "summary": item.get("summary"),
                    "opened": item.get("opened_at"),
                    "resolved": item.get("resolved_at"),
                    "count": item.get("occurrence_count"),
                }
                for item in resolved_findings[:50]
            ],
            use_container_width=True,
            hide_index=True,
        )
