"""Process-start compatibility hooks for PriceGauger runtimes.

Railway stream/worker processes use split stdout/stderr logging so platform severity
matches Python severity. Other processes retain the Streamlit page-link compatibility
guard that originally lived here.
"""
from __future__ import annotations


_worker_logging_configured = False
try:
    from runtime_logging import configure_railway_runtime_logging_if_applicable

    _worker_logging_configured = configure_railway_runtime_logging_if_applicable()
except Exception:
    # Startup observability must never prevent the application from starting.
    _worker_logging_configured = False


if not _worker_logging_configured:
    try:
        import streamlit as st

        _original_page_link = st.page_link

        def _safe_page_link(page, *args, **kwargs):
            try:
                return _original_page_link(page, *args, **kwargs)
            except KeyError:
                st.info("Åpne navigasjonen med » øverst til venstre og velg «Historical Event Lab».")
                return None

        st.page_link = _safe_page_link
    except Exception:
        # Non-Streamlit local tooling must also remain unaffected by sitecustomize.
        pass
