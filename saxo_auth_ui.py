from __future__ import annotations

from datetime import datetime

import streamlit as st

from saxo_auth import SaxoAuthError, configured_oauth_client


def _format_remaining(seconds: int | None) -> str:
    if seconds is None:
        return "ukjent"
    if seconds <= 0:
        return "utløpt"
    minutes = seconds // 60
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} t {minutes} min"
    return f"{minutes} min"


def handle_saxo_oauth_callback() -> None:
    """Consume Saxo's callback query once and persist the resulting token pair."""

    code = str(st.query_params.get("code", "") or "")
    returned_state = str(st.query_params.get("state", "") or "")
    oauth_error = str(st.query_params.get("error", "") or "")
    if not code and not oauth_error:
        return

    client = configured_oauth_client()
    if client is None:
        st.error("Saxo OAuth-callback mottatt, men SAXO_APP_KEY, SAXO_APP_SECRET eller SAXO_REDIRECT_URI mangler.")
        return

    expected_state = str(st.session_state.get("saxo_oauth_state", "") or "")
    if oauth_error:
        st.error(f"Saxo-innloggingen ble avbrutt: {oauth_error}")
    elif not expected_state or returned_state != expected_state:
        st.error("Saxo OAuth state stemte ikke. Start innloggingen på nytt fra samme nettleserfane.")
    else:
        try:
            client.exchange_code(code)
            st.session_state["saxo_oauth_connected"] = True
            st.success("Saxo SIM er koblet til. Access-token fornyes nå automatisk.")
        except SaxoAuthError as exc:
            st.error(f"Kunne ikke fullføre Saxo-innloggingen: {exc}")

    st.session_state.pop("saxo_oauth_state", None)
    for key in ("code", "state", "error", "error_description"):
        if key in st.query_params:
            del st.query_params[key]


def render_saxo_auth_panel() -> None:
    client = configured_oauth_client()
    with st.expander("Saxo OpenAPI", expanded=False):
        if client is None:
            st.caption("OAuth er ikke konfigurert.")
            st.code(
                'SAXO_APP_KEY = "..."\n'
                'SAXO_APP_SECRET = "..."\n'
                'SAXO_REDIRECT_URI = "http://localhost:8501"\n'
                'SAXO_ENVIRONMENT = "sim"',
                language="toml",
            )
            return

        try:
            status = client.status()
        except SaxoAuthError as exc:
            st.error(str(exc))
            status = {"connected": False, "status": "TOKEN_STORE_INVALID", "environment": client.config.environment}

        environment = str(status.get("environment", client.config.environment)).upper()
        st.write(f"**Miljø:** {environment}")
        if status.get("connected"):
            st.success("Tilkoblet · automatisk tokenfornyelse aktiv")
            st.caption(
                "Access-token: "
                + _format_remaining(status.get("access_seconds_remaining"))
                + " · Refresh-sesjon: "
                + _format_remaining(status.get("refresh_seconds_remaining"))
            )
            c1, c2 = st.columns(2)
            if c1.button("Forny nå", key="saxo_refresh_now", use_container_width=True):
                try:
                    client.refresh()
                    st.success("Tokenparet ble fornyet.")
                    st.rerun()
                except SaxoAuthError as exc:
                    st.error(str(exc))
            if c2.button("Koble fra", key="saxo_disconnect", use_container_width=True):
                client.disconnect()
                st.rerun()
        else:
            if status.get("status") == "REAUTH_REQUIRED":
                st.warning("Refresh-sesjonen er utløpt. Ny innlogging kreves.")
            else:
                st.info("Ikke koblet til Saxo.")
            authorization_url, state = client.build_authorization_url()
            st.session_state["saxo_oauth_state"] = state
            st.link_button("Koble til Saxo SIM", authorization_url, use_container_width=True)
            st.caption("Saxo sender nettleseren tilbake til den registrerte redirect-URL-en etter innlogging.")
