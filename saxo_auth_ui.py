from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time

import streamlit as st

from saxo_auth import SaxoAuthError, configured_oauth_client


_STATE_MAX_AGE_SECONDS = 10 * 60


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


def _state_signature(payload: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def build_signed_oauth_state(secret: str, *, now: int | None = None) -> str:
    """Create a short-lived state value that survives leaving the Streamlit page.

    Streamlit session state is tied to its websocket. Navigating to Saxo and back can
    create a new websocket, so a callback must not depend solely on session_state.
    """

    timestamp = int(time.time() if now is None else now)
    nonce = secrets.token_urlsafe(24)
    payload = f"{timestamp}.{nonce}"
    return f"{payload}.{_state_signature(payload, secret)}"


def valid_signed_oauth_state(
    value: str,
    secret: str,
    *,
    now: int | None = None,
    max_age_seconds: int = _STATE_MAX_AGE_SECONDS,
) -> bool:
    try:
        timestamp_text, nonce, signature = value.split(".", 2)
        timestamp = int(timestamp_text)
    except (AttributeError, TypeError, ValueError):
        return False
    if not nonce or not signature:
        return False
    current = int(time.time() if now is None else now)
    age = current - timestamp
    if age < -30 or age > max_age_seconds:
        return False
    payload = f"{timestamp}.{nonce}"
    expected = _state_signature(payload, secret)
    return hmac.compare_digest(signature, expected)


def _clear_oauth_query_params() -> None:
    for key in ("code", "state", "error", "error_description"):
        if key in st.query_params:
            del st.query_params[key]


def handle_saxo_oauth_callback() -> None:
    """Consume Saxo's callback query once and persist the resulting token pair."""

    code = str(st.query_params.get("code", "") or "")
    returned_state = str(st.query_params.get("state", "") or "")
    oauth_error = str(st.query_params.get("error", "") or "")
    error_description = str(st.query_params.get("error_description", "") or "")
    if not code and not oauth_error:
        return

    client = configured_oauth_client()
    if client is None:
        st.error("Saxo OAuth-callback mottatt, men SAXO_APP_KEY, SAXO_APP_SECRET eller SAXO_REDIRECT_URI mangler.")
        _clear_oauth_query_params()
        return

    if oauth_error:
        detail = error_description or oauth_error
        st.error(f"Saxo-innloggingen ble avbrutt: {detail}")
    elif not valid_signed_oauth_state(returned_state, client.config.client_secret):
        st.error("Saxo OAuth state var ugyldig eller utløpt. Start innloggingen på nytt fra Saxo OpenAPI-siden.")
    else:
        try:
            client.exchange_code(code)
            st.session_state["saxo_oauth_connected"] = True
            st.success("Saxo SIM er koblet til. Access-token fornyes nå automatisk.")
        except SaxoAuthError as exc:
            st.error(f"Kunne ikke fullføre Saxo-innloggingen: {exc}")

    _clear_oauth_query_params()


def render_saxo_auth_panel() -> None:
    client = configured_oauth_client()
    with st.expander("Saxo OpenAPI", expanded=False):
        if client is None:
            st.caption("OAuth er ikke konfigurert.")
            st.code(
                'SAXO_APP_KEY = "..."\n'
                'SAXO_APP_SECRET = "..."\n'
                'SAXO_REDIRECT_URI = "http://localhost:8501/Saxo_OpenAPI"\n'
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
            state = build_signed_oauth_state(client.config.client_secret)
            authorization_url, _ = client.build_authorization_url(state=state)
            st.link_button("Koble til Saxo SIM", authorization_url, use_container_width=True)
            st.caption("Saxo sender nettleseren tilbake til den registrerte redirect-URL-en etter innlogging.")
