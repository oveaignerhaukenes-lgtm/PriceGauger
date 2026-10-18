"""Persistent broker-authoritative Saxo statistics, not paper/sim P&L."""
from __future__ import annotations

from datetime import date, timedelta
from io import StringIO
import csv

import pandas as pd
import streamlit as st

from autotrader_v3_saxo_history_v1 import load_saxo_history_stats_v1


def render_v3_saxo_statistics_v1(*, db_path="pricegauger.db"):
    st.subheader("Saxo · historisk kontostatistikk")
    st.caption(
        "Leses automatisk fra Saxo Account History, lagres i PriceGauger/PostgreSQL. "
        "Dagsverdier oppdateres etter Saxos sluttoppgjør; dette er ikke LIVE-P/L."
    )
    try:
        data = load_saxo_history_stats_v1(
            db_path=db_path, from_day=date.today() - timedelta(days=35)
        )
    except Exception as exc:
        st.warning("Saxo-historikk kan ikke leses nå: " + type(exc).__name__)
        return

    days = data["days"]
    if not days:
        st.info(
            "Ingen bekreftede Saxo-dagsdata er lagret ennå. "
            "Worker forsøker automatisk innlesing; ingen skjema eller manuell import trengs."
        )
        return

    tx = {(r["account_id"],r["day"]):r for r in data["transactions"]}
    cp = {(r["account_id"],r["day"]):r for r in data["closed_positions"]}
    display = []
    for d in days:
        a = d["account_id"]
        t = tx.get((a,d["day"]))
        c = cp.get((a,d["day"]))
        pnl = None if not t else t["realized_pnl"]
        currency = str(d["account_currency"] or "")
        tx_currency = "" if not t else str(t["currency"] or "")
        display.append({
            "Dato": d["day"],
            "Saxo-konto": a,
            "Valuta NAV": currency or "ukjent",
            "Kontoverdi EOD": d["nav"],
            "Kontantstrøm": d["cash_transfer"],
            "NAV-endring eks. kontantstrøm": d["nav_change_ex_cash"],
            "TWR dag %": None if d["daily_twr"] is None else d["daily_twr"] * 100,
            "Realisert P/L (bokført)": pnl,
            "Valuta transaksjoner": tx_currency or "ukjent",
            "Transaksjoner": 0 if not t else t["transactions"],
            "Lukkede posisjoner": 0 if not c else c["closed_positions"],
            "Saxo synk": d["last_success"] or "ukjent",
        })
    frame = pd.DataFrame(display)
    st.dataframe(frame, use_container_width=True, hide_index=True)
    st.caption(
        "VIKTIG: NAV-endring er ikke det samme som realisert trading-P/L. "
        "TWR er Saxos tidsvektede kontoretur. Realisert P/L og kostnader i "
        "transaksjonstabellen oppgis separat; de må ikke trekkes dobbelt. "
        "Valutaer kan være ulike, og hele Saxo-kontoen kan inneholde mer enn én strategi."
    )
    st.download_button(
        "Last ned lagrede Saxo-statistikker (CSV)",
        data=frame.to_csv(index=False).encode("utf-8-sig"),
        file_name="pricegauger_saxo_account_daily.csv",
        mime="text/csv",
        key="v3_saxo_eod_download",
    )


__all__ = ["render_v3_saxo_statistics_v1"]
