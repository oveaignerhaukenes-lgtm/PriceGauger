from __future__ import annotations

import streamlit as st


def get_secret(name: str) -> str:
    """Return a configured secret without ever logging or displaying its value."""
    value = st.secrets.get(name, "")
    return str(value).strip() if value else ""


def gdelt_api_key() -> str:
    return get_secret("GDELT_CLOUD_API_KEY")


def twelve_data_api_key() -> str:
    return get_secret("TWELVE_DATA_API_KEY")
