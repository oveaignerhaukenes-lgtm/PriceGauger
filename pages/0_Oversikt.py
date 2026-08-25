from __future__ import annotations

from datetime import datetime

import streamlit as st

from analysis_status import AnalysisStatusStore
from analysis_status_ui import ANALYSIS_STATUS_CSS, render_analysis_status
from build_info import render_build_badge
from context_overview_read_model_v2 import load_context_overview_v2
from market_navigation import market_detail_href
from overview_v2_cards import render_v2_overview_market_cards
from overview_visuals import asset_color
from saxo_auth import configured_oauth_client


st.set_page_config(page_title="Oversikt · PriceGauger", page_icon="📡", layout="wide")

render_build_badge()
title_col, saxo_col = st.columns([4, 1])
with title_col:
    st.title("PriceGauger")
    st.caption("Canonical v2 markedstilstand · Technical Core og Context holdes uavhengige frem til composition.")
with saxo_col:
    try:
        _saxo_client = configured_oauth_client()
        _saxo_status = _saxo_client.status() if _saxo_client is not None else {
            "connected": False,
            "environment": "ukjent",
            "status": "NOT_CONFIGURED",
        }
    except Exception:
        _saxo_status = {"connected": False, "environment": "ukjent", "status": "STATUS_ERROR"}
    _saxo_icon = "🟢" if _saxo_status.get("connected") else "🔴"
    st.markdown(f"**{_saxo_icon} Saxo · {str(_saxo_status.get('environment', 'ukjent')).upper()}**")
    st.caption(str(_saxo_status.get("status", "UKJENT")).replace("_", " "))
    st.page_link("pages/1_Saxo_OpenAPI.py", label="Åpne Saxo-status", icon="🔌")

st.markdown(f"<style>{ANALYSIS_STATUS_CSS}</style>", unsafe_allow_html=True)

refresh_col, refresh_note_col = st.columns([1, 4])
with refresh_col:
    st.button("Oppdater nå", key="overview-manual-refresh", use_container_width=True)
with refresh_note_col:
    st.caption("Oversikt oppdateres ved brukerhandling/refresh. Ingen automatisk redraw av grafkort mens du leser siden.")


def _render_analysis_status() -> None:
    progress_html = render_analysis_status(AnalysisStatusStore().load())
    if progress_html:
        st.markdown(progress_html, unsafe_allow_html=True)


_render_analysis_status()


def _fmt_time(value: str) -> str:
    if not value:
        return "—"
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).strftime("%d.%m.%y · %H:%M")
    except Exception:
        return str(value)


def _signed(value: float) -> str:
    return f"{float(value):+.2f}"


def _render_context_v2() -> None:
    try:
        context = load_context_overview_v2()
    except Exception as exc:
        st.warning(f"Context v2 kunne ikke leses: {exc}")
        return

    st.subheader("Semantisk kontekst · v2")
    if context is None:
        st.info("Venter på første canonical ContextSnapshotV2 fra Telegram/News Context Engine.")
        return

    status = str(context.freshness_status).upper()
    status_text = "FERSK" if status == "FRESH" else status
    header_a, header_b, header_c = st.columns([2.3, 1.0, 1.4])
    with header_a:
        st.markdown(f"### {context.regime_label or 'Uklassifisert regime'}")
        st.write(context.summary or "Context Engine har ingen samlet tekstlig oppsummering i dette snapshotet.")
    with header_b:
        st.metric("Freshness", status_text)
    with header_c:
        st.metric("Targets", len(context.targets))

    st.caption(
        f"ContextSnapshotV2 · {_fmt_time(context.as_of)} · engine {context.engine_version} · "
        f"coverage {_fmt_time(context.coverage_start)} → {_fmt_time(context.coverage_end)}"
    )
    if status != "FRESH":
        st.warning("Context er ikke FRESH. Holistic Composer skal derfor ikke bruke dette snapshotet til å endre Technical baseline.")

    if context.targets:
        st.markdown("**Markedskontekst**")
        rows = [
            {
                "Marked": target.target_key,
                "Retning": target.direction_label,
                "Bias": _signed(target.directional_bias),
                "Confidence": f"{target.confidence:.0%}",
                "Novelty": f"{target.novelty:.0%}",
                "Event risk": f"{target.event_risk:.0%}",
                "Context summary": target.summary,
            }
            for target in context.targets
        ]
        st.dataframe(rows, hide_index=True, use_container_width=True)
    else:
        st.caption("Ingen markedsspesifikke Context-targets i siste snapshot.")

    with st.expander("Context evidence / provenance", expanded=False):
        if not context.evidence:
            st.write("Ingen evidence-referanser i dette snapshotet.")
        else:
            evidence_rows = [
                {
                    "Kilde": item.source_kind,
                    "Scope": item.source_scope,
                    "Source ID": item.source_id,
                    "Publisert": _fmt_time(item.published_at),
                    "Observert": _fmt_time(item.observed_at),
                    "Tags": ", ".join(item.tags),
                    "User scope": item.user_scope_id or "—",
                    "Evidence ID": item.evidence_id,
                }
                for item in context.evidence[:50]
            ]
            st.dataframe(evidence_rows, hide_index=True, use_container_width=True)
        st.caption(f"snapshot_id {context.snapshot_id}")


def _render_live_market_cards() -> None:
    render_v2_overview_market_cards(
        st,
        asset_color=asset_color,
        market_detail_href=market_detail_href,
    )


_render_context_v2()

st.divider()
st.subheader("Teknisk analyse og prognose · v2")
_render_live_market_cards()

st.caption(
    "Overview leser canonical ContextSnapshotV2 for semantisk kontekst og canonical v2 workspace for Technical Core. "
    "Legacy Information/Decision/Recommendation brukes ikke som skjult Overview-fallback."
)
