from __future__ import annotations

import streamlit as st


# Streamlit Cloud can raise KeyError when a page exists in the repository but
# is not present in the runtime page registry. Patch the already-imported
# Streamlit module here because app.py imports config.py before calling
# st.page_link().
_original_page_link = st.page_link


def _safe_page_link(page, *args, **kwargs):
    try:
        return _original_page_link(page, *args, **kwargs)
    except KeyError:
        st.info(
            "Siden er ikke registrert av denne Streamlit-instansen. "
            "Åpne navigasjonen med » øverst til venstre og velg «Historical Event Lab»."
        )
        return None


st.page_link = _safe_page_link


def get_secret(name: str) -> str:
    """Return a configured secret without ever logging or displaying its value."""
    value = st.secrets.get(name, "")
    return str(value).strip() if value else ""


def gdelt_api_key() -> str:
    return get_secret("GDELT_CLOUD_API_KEY")


def twelve_data_api_key() -> str:
    return get_secret("TWELVE_DATA_API_KEY")
