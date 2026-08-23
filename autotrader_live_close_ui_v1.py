from __future__ import annotations

import streamlit as st

from autotrader_live_close_v1 import (
    LiveCloseConfigV1,
    code_gate_enabled_v1,
    ensure_live_close_schema_v1,
    load_live_close_config_v1,
    run_live_close_cycle_v1,
    save_live_close_config_v1,
)
from database import connect, using_postgres
from saxo_provider import LIVE_BASE_URL, configured_client


def _rows(sql: str, params=()) -> list[dict[str, object]]:
    with connect() as db:
        result = db.execute(sql, params).fetchall()
    rows: list[dict[str, object]] = []
    for row in result:
        try:
            rows.append(dict(row))
        except Exception:
            continue
    return rows


def render_live_close_v1() -> None:
    st.subheader("LIVE close-only · proof of concept")
    st.caption(
        "Denne modulen kan bare redusere en allerede åpen, trigget posisjon. Den kan ikke åpne posisjoner, "
        "øke størrelse eller drive entry-strategi. Automatisk Saxo-ordre bruker ManualOrder=false."
    )

    if not using_postgres():
        st.info("LIVE close-only krever PostgreSQL-runtime.")
        return

    try:
        ensure_live_close_schema_v1()
        config = load_live_close_config_v1()
    except Exception as exc:
        st.error(f"LIVE close-only kunne ikke initialiseres: {exc}")
        return

    client = configured_client()
    environment_ok = bool(client and client.base_url.rstrip("/").lower() == LIVE_BASE_URL.lower())
    code_gate = code_gate_enabled_v1()

    c1, c2, c3 = st.columns(3)
    c1.metric("Saxo-miljø", "LIVE" if environment_ok else "IKKE LIVE")
    c2.metric("Kode-gate", "ÅPEN" if code_gate else "LÅST")
    c3.metric("Execution", "ARMERT" if config.armed and code_gate and environment_ok else "AV")

    st.info(
        "To nøkler kreves for faktisk ordre: Railway-kodegaten og denne armeringen. "
        "Hvis én av dem er av, blir ingen LIVE-ordre sendt."
    )

    acknowledge = st.checkbox(
        "Jeg forstår at armering kan sende en automatisk markedsordre for å lukke en trigget LIVE-posisjon.",
        value=False,
    )
    desired = st.checkbox("Armér automatisk LIVE close-only", value=config.armed)
    if st.button("Lagre LIVE execution-status", width="stretch"):
        if desired and not acknowledge:
            st.error("Bekreft LIVE execution-advarselen før armering.")
        elif desired and not environment_ok:
            st.error("Armering avvises fordi Saxo-klienten ikke peker på LIVE.")
        else:
            save_live_close_config_v1(LiveCloseConfigV1(armed=bool(desired)))
            st.success("LIVE close-only-status er lagret.")
            st.rerun()

    if st.button("Diagnostiser Saxo execution-forutsetninger", width="stretch"):
        if not environment_ok or client is None:
            st.error("Saxo LIVE-klient er ikke tilgjengelig.")
        else:
            try:
                profile = client._get("port/v1/clients/me")
                accounts = client._get("port/v1/accounts/me").get("Data") or []
                st.write(
                    {
                        "PositionNettingMode": profile.get("PositionNettingMode"),
                        "PositionNettingMethod": profile.get("PositionNettingMethod"),
                        "ReduceExposureOnly": profile.get("ReduceExposureOnly"),
                        "ActiveAccounts": sum(1 for row in accounts if isinstance(row, dict) and row.get("Active", True)),
                    }
                )
                if str(profile.get("PositionNettingMode") or "").lower() != "intraday":
                    st.warning(
                        "PoC-executoren krever Intraday netting. Den sender ikke ordre i EndOfDay-mode."
                    )
                else:
                    st.success("Intraday netting er aktiv; close-only-netting kan verifiseres end-to-end.")
            except Exception as exc:
                st.error(f"Saxo execution-diagnostikk feilet: {exc}")

    if st.button("Kjør close-only cycle nå", width="stretch"):
        try:
            summary = run_live_close_cycle_v1()
            st.write(summary)
        except Exception as exc:
            st.error(f"LIVE close-only cycle feilet: {exc}")

    try:
        attempts = _rows(
            """
            SELECT event_id, net_position_id AS position, uic, asset_type, close_side,
                   amount, status, order_id, precheck_result, error_message,
                   created_at, updated_at
            FROM pg_v2_autotrader_live_close_attempts
            ORDER BY created_at DESC
            LIMIT 20
            """
        )
    except Exception as exc:
        st.caption(f"Execution-audit er ikke tilgjengelig: {exc}")
        return

    if attempts:
        with st.expander("LIVE close audit", expanded=True):
            st.dataframe(attempts, width="stretch", hide_index=True)
    else:
        st.caption("Ingen LIVE close-forsøk er registrert.")
