from __future__ import annotations

import streamlit as st

from autotrader_live_close_v1 import (
    LiveCloseConfigV1,
    code_gate_enabled_v1,
    load_live_close_config_v1,
    run_live_close_cycle_v1,
    save_live_close_config_v1,
)
from autotrader_managed_positions_v1 import (
    enroll_position_v1,
    is_position_managed_v1,
    stop_managing_position_v1,
)
from autotrader_risk_control_v2 import _position_observations_v2
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


def _render_position_enrollment(client) -> None:
    st.markdown("#### Åpne posisjoner")
    st.caption(
        "Nye posisjoner tas aldri automatisk over. Trykk **Auto-manage** på akkurat den posisjonen "
        "PriceGauger skal få lov til å håndtere. Hvis posisjonen lukkes, åpnes på nytt eller størrelsen "
        "endres, må den eksplisitt Auto-manages på nytt."
    )
    if client is None:
        st.info("Saxo-klienten er ikke tilgjengelig.")
        return
    try:
        observations = _position_observations_v2(client)
    except Exception as exc:
        st.error(f"Kunne ikke lese åpne Saxo-posisjoner: {exc}")
        return
    if not observations:
        st.caption("Ingen åpne Saxo-posisjoner akkurat nå.")
        return

    for observation in observations:
        managed = is_position_managed_v1(observation)
        left, middle, right = st.columns([5, 2, 2])
        left.write(
            f"**{observation.asset_type} · UIC {observation.uic}**  \n"
            f"{observation.direction} · amount {observation.amount:g} · "
            f"posisjonsavkastning {observation.pnl_pct:+.2f}%"
        )
        middle.metric("Status", "AUTO-MANAGED" if managed else "MANUELL")
        key = f"manage-{observation.account_id}-{observation.net_position_id}"
        if managed:
            if right.button("Stopp auto-manage", key=key, width="stretch"):
                stop_managing_position_v1(observation.account_id, observation.net_position_id)
                st.success("Auto-manage er slått av for denne posisjonen.")
                st.rerun()
        else:
            if right.button("Auto-manage", key=key, type="primary", width="stretch"):
                enroll_position_v1(observation)
                st.success("Denne posisjonen er nå eksplisitt valgt for Auto-manage.")
                st.rerun()


def render_live_close_v1() -> None:
    st.subheader("LIVE close-only · proof of concept")
    st.caption(
        "Execution-motoren kan bare redusere en allerede åpen, eksplisitt Auto-managed posisjon. "
        "Den kan ikke åpne posisjoner, øke størrelse eller drive entry-strategi."
    )

    if not using_postgres():
        st.info("LIVE close-only krever PostgreSQL-runtime.")
        return

    try:
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
    c3.metric("Execution-motor", "PÅ" if config.armed and code_gate and environment_ok else "AV")

    st.info(
        "Tre ting kreves før en ordre kan sendes: Railway-kodegaten, execution-motoren og eksplisitt "
        "Auto-manage på den enkelte posisjonen. En ny posisjon er alltid MANUELL som standard."
    )

    acknowledge = st.checkbox(
        "Jeg forstår at execution-motoren kan sende en automatisk markedsordre, men bare for posisjoner jeg eksplisitt har valgt med Auto-manage.",
        value=False,
    )
    desired = st.checkbox("Aktiver LIVE close-motor", value=config.armed)
    if st.button("Lagre execution-motor", width="stretch"):
        if desired and not acknowledge:
            st.error("Bekreft LIVE execution-advarselen før motoren aktiveres.")
        elif desired and not environment_ok:
            st.error("Aktivering avvises fordi Saxo-klienten ikke peker på LIVE.")
        else:
            save_live_close_config_v1(LiveCloseConfigV1(armed=bool(desired)))
            st.success("LIVE close-motorstatus er lagret.")
            st.rerun()

    _render_position_enrollment(client)

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
            SELECT attempts.event_id,
                   attempts.net_position_id AS position,
                   attempts.uic,
                   attempts.asset_type,
                   events.reason AS trigger,
                   events.pnl_pct AS trigger_pnl_pct,
                   events.hard_stop_pct,
                   events.created_at AS triggered_at,
                   attempts.close_side,
                   attempts.amount,
                   attempts.status,
                   attempts.order_id,
                   attempts.precheck_result,
                   attempts.error_message,
                   attempts.created_at AS attempted_at,
                   attempts.updated_at
            FROM pg_v2_autotrader_live_close_attempts AS attempts
            LEFT JOIN pg_v2_autotrader_risk_events AS events
              ON events.event_id = attempts.event_id
            ORDER BY attempts.created_at DESC
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
