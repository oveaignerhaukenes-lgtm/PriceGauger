from __future__ import annotations

import streamlit as st

from autotrader_pilot_status_v1 import load_pilot_status_v1
from trading_desk_v2_context import TradingDeskV2Context
from tradingdesk_automanager_simple_v1 import _active_live_for_context_v1, _direction_v1, _exact_observation_v1
from autotrader_risk_control_v2 import PositionObservationV2, _position_observations_v2
from saxo_provider import configured_client


def _fmt_money_v1(value: float, currency: str) -> str:
    return f"{value:,.2f} {currency}".replace(",", " ")


def render_tradingdesk_pilot_status_panel_v1(
    context: TradingDeskV2Context,
    *,
    observations: tuple[PositionObservationV2, ...] | None = None,
) -> None:
    """Show audited pilot capital/trade status without acquiring execution authority."""
    client = configured_client()
    if client is None:
        return
    try:
        enrollment = _active_live_for_context_v1(context)
        if enrollment is None:
            return
        status = load_pilot_status_v1(enrollment.pilot_key)
        current_observations = observations if observations is not None else _position_observations_v2(client)
        observation = _exact_observation_v1(enrollment, current_observations)
        direction = _direction_v1(observation)
    except Exception as exc:
        st.caption(f"Pilotstatus venter: {exc}")
        return

    with st.container(border=True):
        st.markdown("**Pilotstatus**")
        seed_col, equity_col, pnl_col = st.columns(3, gap="small")
        seed_col.metric("Seed", _fmt_money_v1(status.seed_capital, status.currency))
        equity_col.metric("Equity", _fmt_money_v1(status.equity, status.currency))
        pnl_col.metric(
            "Realisert P/L",
            _fmt_money_v1(status.realized_net_pnl, status.currency),
            delta=f"{status.return_pct:+.1f}%",
        )

        win_rate = "–" if status.win_rate_pct is None else f"{status.win_rate_pct:.1f}%"
        current_amount = 0.0 if observation is None else abs(float(observation.amount))
        cohort_note = "" if status.cohort_count <= 1 else f" · Cohorts {status.cohort_count}"
        st.caption(
            f"Trades {status.closed_trades} · W {status.wins} / L {status.losses} / BE {status.breakeven} · "
            f"Win rate {win_rate} · Nå {direction} {current_amount:g}{cohort_note}"
        )

        if status.last_open_amount is not None:
            utilization = (
                "ukjent"
                if status.capital_utilization_pct is None
                else f"{status.capital_utilization_pct:.1f}% av pilotbudsjettet i initial margin"
            )
            last_budget = (
                "ukjent budsjett"
                if status.last_open_budget is None
                else _fmt_money_v1(status.last_open_budget, status.currency)
            )
            st.caption(
                f"Siste OPEN: amount {status.last_open_amount:g} · budget {last_budget} · {utilization} · "
                f"status {status.last_open_status or 'ukjent'}"
            )

        threshold = status.harvest_threshold
        if status.equity < threshold:
            st.caption(
                f"Compounding aktiv · høsting planlegges først ved 2× seed = "
                f"{_fmt_money_v1(threshold, status.currency)}."
            )
        else:
            st.caption(
                f"2× seed er nådd ({_fmt_money_v1(threshold, status.currency)}). "
                "Høstefunksjonen er ennå ikke aktivert."
            )


__all__ = ["render_tradingdesk_pilot_status_panel_v1"]
