from __future__ import annotations

import streamlit as st

from autotrader_macd_dry_run_v2 import STRATEGY_KEY
from database import connect, using_postgres


def _rows(sql: str, params=()) -> list[dict[str, object]]:
    with connect() as db:
        result = db.execute(sql, params).fetchall()
    rows: list[dict[str, object]] = []
    for row in result:
        if isinstance(row, dict):
            rows.append(dict(row))
        else:
            try:
                rows.append(dict(row))
            except Exception:
                continue
    return rows


def render_macd_dry_run_monitor_v2() -> None:
    st.subheader("30m MACD · LONG / FLAT dry-run")
    st.caption(
        "Observerer bare lukkede 30m-candles med MACD 12/26/9. "
        "CROSS_UP gir WOULD_BUY fra FLAT; CROSS_DOWN gir WOULD_SELL_ALL fra LONG. "
        "Denne fasen sender ingen Saxo-ordre."
    )
    if not using_postgres():
        st.info("Dry-run monitor krever PostgreSQL-runtime.")
        return
    try:
        states = _rows(
            """
            SELECT m.name AS market, s.position_state, s.last_evaluated_bar_time,
                   s.last_signal_bar_time, s.updated_at
            FROM pg_v2_autotrader_strategy_state s
            JOIN pg_v2_markets m ON m.market_id = s.market_id
            WHERE s.strategy_key = ?
            ORDER BY m.name
            """,
            (STRATEGY_KEY,),
        )
        events = _rows(
            """
            SELECT m.name AS market, e.signal_bar_time, e.signal, e.action,
                   e.prior_state, e.desired_state,
                   e.previous_macd, e.previous_signal, e.current_macd, e.current_signal
            FROM pg_v2_autotrader_strategy_events e
            JOIN pg_v2_markets m ON m.market_id = e.market_id
            WHERE e.strategy_key = ?
            ORDER BY e.signal_bar_time DESC
            LIMIT 20
            """,
            (STRATEGY_KEY,),
        )
    except Exception as exc:
        st.info(f"Dry-run state er ikke initialisert ennå: {exc}")
        return

    if not states:
        st.info("Venter på første dry-run-evaluering fra worker.")
        return

    st.dataframe(states, use_container_width=True, hide_index=True)
    if events:
        with st.expander("Siste MACD-kryss", expanded=True):
            st.dataframe(events, use_container_width=True, hide_index=True)
    else:
        st.caption("Ingen MACD-kryss er registrert etter at dry-run-state ble startet.")
