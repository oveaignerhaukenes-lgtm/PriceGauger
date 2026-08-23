from __future__ import annotations

import streamlit as st

from autotrader_risk_dry_run_v2 import (
    RiskConfigV2,
    load_risk_config_v2,
    run_risk_dry_run_cycle_v2,
    save_risk_config_v2,
)
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


def render_risk_dry_run_monitor_v2() -> None:
    st.subheader("Risk-control · dry-run")
    st.caption(
        "Leser åpne Saxo-posisjoner og simulerer bare exit-beslutninger. "
        "Ingen pre-check eller ordreplassering finnes i denne modulen. "
        "Standard: -1,0 % hard stop og trailing fra +2,0 % med 0,5 prosentpoeng avstand."
    )
    if not using_postgres():
        st.info("Risk-control dry-run krever PostgreSQL-runtime.")
        return

    try:
        config = load_risk_config_v2()
    except Exception as exc:
        st.info(f"Risk-control er ikke initialisert ennå: {exc}")
        return

    with st.form("autotrader_risk_config_v2"):
        enabled = st.checkbox(
            "Aktiver overvåking",
            value=config.enabled,
            help="Slår selve dry-run-evalueringen av/på. Sender aldri ordre.",
        )
        c1, c2, c3 = st.columns(3)
        hard_stop_pct = c1.number_input(
            "Hard stop (%)",
            min_value=-25.0,
            max_value=-0.05,
            value=float(config.hard_stop_pct),
            step=0.1,
            format="%.2f",
        )
        trailing_activation_pct = c2.number_input(
            "Trailing aktiveres ved gevinst (%)",
            min_value=0.1,
            max_value=50.0,
            value=float(config.trailing_activation_pct),
            step=0.1,
            format="%.2f",
        )
        trailing_drawdown_pct = c3.number_input(
            "Trailing-avstand (prosentpoeng)",
            min_value=0.05,
            max_value=20.0,
            value=float(config.trailing_drawdown_pct),
            step=0.05,
            format="%.2f",
        )
        trailing_enabled = st.checkbox("Bruk trailing stop", value=config.trailing_enabled)

        c4, c5, c6 = st.columns(3)
        fixed_take_profit_enabled = c4.checkbox(
            "Fast take-profit",
            value=config.fixed_take_profit_enabled,
            help="Valgfri absolutt gevinstgrense i tillegg til trailing stop.",
        )
        fixed_take_profit_pct = c5.number_input(
            "Fast take-profit (%)",
            min_value=0.1,
            max_value=100.0,
            value=float(config.fixed_take_profit_pct),
            step=0.5,
            format="%.2f",
        )
        max_price_delay_minutes = c6.number_input(
            "Maks prisforsinkelse (min)",
            min_value=0,
            max_value=120,
            value=int(config.max_price_delay_minutes),
            step=1,
            help="0 krever realtime pris. Forsinket pris kan observeres, men får ikke WOULD_CLOSE.",
        )
        saved = st.form_submit_button("Lagre risk-control", use_container_width=True)

    if saved:
        try:
            save_risk_config_v2(
                RiskConfigV2(
                    enabled=enabled,
                    hard_stop_pct=float(hard_stop_pct),
                    trailing_enabled=trailing_enabled,
                    trailing_activation_pct=float(trailing_activation_pct),
                    trailing_drawdown_pct=float(trailing_drawdown_pct),
                    fixed_take_profit_enabled=fixed_take_profit_enabled,
                    fixed_take_profit_pct=float(fixed_take_profit_pct),
                    max_price_delay_minutes=int(max_price_delay_minutes),
                )
            )
            st.success("Risk-control-kontrakten er lagret. Eventuelle gamle triggers nullstilles og evalueres på nytt.")
            st.rerun()
        except Exception as exc:
            st.error(f"Kunne ikke lagre risk-control: {exc}")

    if st.button("Kjør read-only evaluering nå", use_container_width=True):
        try:
            summary = run_risk_dry_run_cycle_v2()
            st.success(
                f"Evaluert {summary.observed} åpne posisjoner · "
                f"WOULD_CLOSE {summary.close_signals} · feil {summary.failed}."
            )
            st.rerun()
        except Exception as exc:
            st.error(f"Risk-control-evaluering feilet: {exc}")

    try:
        states = _rows(
            """
            SELECT net_position_id AS position, asset_type, uic, direction, amount,
                   average_open_price, current_price, pnl_pct, high_water_pct,
                   trailing_floor_pct, price_delay_minutes, can_be_closed,
                   calculation_reliability, last_action, last_reason,
                   triggered_reason, triggered_at, last_seen_at
            FROM pg_v2_autotrader_risk_state
            WHERE active = TRUE
            ORDER BY last_seen_at DESC
            """
        )
        events = _rows(
            """
            SELECT net_position_id AS position, asset_type, uic, direction,
                   reason, pnl_pct, high_water_pct, trailing_floor_pct,
                   price_delay_minutes, created_at
            FROM pg_v2_autotrader_risk_events
            ORDER BY created_at DESC
            LIMIT 20
            """
        )
    except Exception as exc:
        st.caption(f"Venter på risk-control-runtime: {exc}")
        return

    if states:
        st.dataframe(states, use_container_width=True, hide_index=True)
    else:
        st.info("Ingen åpne Saxo-posisjoner observert akkurat nå.")

    if events:
        with st.expander("Siste WOULD_CLOSE-hendelser", expanded=True):
            st.dataframe(events, use_container_width=True, hide_index=True)
