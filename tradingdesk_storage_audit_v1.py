from __future__ import annotations

import streamlit as st

from storage_learning_audit_v1 import capture_storage_audit_v1


def _mb(value: int | float | None) -> str:
    if value is None:
        return "—"
    return f"{float(value) / (1024 * 1024):,.1f} MB"


def render_tradingdesk_storage_audit_v1() -> None:
    """Show non-destructive storage growth evidence collected at most once per day."""
    with st.expander("Storage & Learning Audit", expanded=False):
        st.caption(
            "Læreperiode: måler hva som faktisk vokser før vi bestemmer retention. "
            "Ingen data slettes eller komprimeres av denne auditen."
        )
        try:
            summary = capture_storage_audit_v1()
        except Exception as exc:
            st.caption(f"Storage-audit venter: {exc}")
            return
        if summary is None:
            st.caption("Storage-audit krever PostgreSQL.")
            return

        cols = st.columns(4)
        cols[0].metric("Database", _mb(summary.database_bytes))
        cols[1].metric("Tabeller + indekser", _mb(summary.relations_total_bytes))
        cols[2].metric("Relasjoner", str(summary.relation_count))
        cols[3].metric("Målt", summary.captured_at.strftime("%Y-%m-%d %H:%M UTC"))

        rows = []
        for item in summary.relations[:20]:
            rows.append({
                "datasett": item.relation_name,
                "rader (est.)": item.row_estimate,
                "tabell": _mb(item.table_bytes),
                "indekser": _mb(item.index_bytes),
                "totalt": _mb(item.total_bytes),
                "vekst siden sist": _mb(item.growth_bytes),
                "estimert/døgn": _mb(item.growth_per_day_bytes),
            })
        if rows:
            st.dataframe(rows, width="stretch", hide_index=True)
        st.caption(
            "Målet er å skille felles rådata fra rekonstruerbare read-models og duplisert kontekst. "
            "Når vi har nok historikk kan retention settes ut fra faktisk læringsverdi og vekst, ikke gjetning."
        )


__all__ = ["render_tradingdesk_storage_audit_v1"]
