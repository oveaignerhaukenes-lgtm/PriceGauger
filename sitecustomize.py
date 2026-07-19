"""Runtime compatibility guard for Streamlit page links.

Some Streamlit Cloud builds raise KeyError when st.page_link targets a page
that exists in the repository but was not registered in the current page
registry. Keep the app alive and direct the user to the built-in navigation.
"""
from __future__ import annotations

import streamlit as st

_original_page_link = st.page_link


def _safe_page_link(page, *args, **kwargs):
    try:
        return _original_page_link(page, *args, **kwargs)
    except KeyError:
        st.info("Åpne navigasjonen med » øverst til venstre og velg «Historical Event Lab».")
        return None


st.page_link = _safe_page_link
