from __future__ import annotations

import os

import streamlit as st


_original_page_link = st.page_link


def _safe_page_link(page, *args, **kwargs):
    try:
        return _original_page_link(page, *args, **kwargs)
    except KeyError:
        st.info("Siden er ikke registrert av denne Streamlit-instansen. Åpne navigasjonen med » øverst til venstre.")
        return None


st.page_link = _safe_page_link


def get_secret(name: str) -> str:
    """Return a configured secret without ever logging or displaying its value."""
    environment_value = os.getenv(name, "").strip()
    if environment_value:
        return environment_value
    try:
        value = st.secrets.get(name, "")
    except Exception:
        # Local development may not have a .streamlit/secrets.toml file.
        return ""
    return str(value).strip() if value else ""


def gdelt_provider() -> str:
    return (get_secret("GDELT_PROVIDER") or "direct").lower()


def gdelt_api_key() -> str:
    provider = gdelt_provider()
    if provider == "direct":
        return "__DIRECT__"
    if provider == "auto":
        return get_secret("GDELT_CLOUD_API_KEY") or "__DIRECT__"
    if provider == "cloud":
        return get_secret("GDELT_CLOUD_API_KEY")
    return "__DIRECT__"


def twelve_data_api_key() -> str:
    return get_secret("TWELVE_DATA_API_KEY")


def openai_api_key() -> str:
    return get_secret("OPENAI_API_KEY")


def openai_market_model() -> str:
    return get_secret("OPENAI_MARKET_MODEL") or "gpt-5-mini"
