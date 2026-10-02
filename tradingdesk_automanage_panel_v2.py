from __future__ import annotations

# Canonical facade: live controls and persisted analysis use explicit modules.
import streamlit as st

from autotrader_pnl_comparison_v2 import load_automanager_pnl_comparison_v2
from autotrader_strategy_enrollment_v2 import EXECUTION_MODE_LIVE
from database import using_postgres
from trading_desk_v2_context import TradingDeskV2Context
from tradingdesk_automanage_activity_ui_v2 import render_automanager_activity_log_v2
from tradingdesk_automanage_read_model_v2 import AutoManagePanelSnapshotV2, pnl_enrollments_for_context_v2
from tradingdesk_automanager_close_control_v1 import render_close_position_control_v1
from tradingdesk_automanager_simple_v1 import render_tradingdesk_automanager_simple_v1
from tradingdesk_chart_trade_controls_v1 import render_tradingdesk_chart_trade_controls_v1
from tradingdesk_hybrid_lab_v1 import render_tradingdesk_hybrid_lab_v1
from tradingdesk_macd_supervisor_lab_v1 import render_tradingdesk_macd_supervisor_lab_v1
from tradingdesk_pilot_status_panel_v1 import render_tradingdesk_pilot_status_panel_v1
from tradingdesk_storage_audit_v1 import render_tradingdesk_storage_audit_v1
from tradingdesk_strategy_scoreboard_v1 import render_tradingdesk_strategy_scoreboard_v1
from tradingdesk_three_trader_lab_v1 import render_tradingdesk_three_trader_lab_v1
from tradingdesk_ui.charts.lightweight.pnl_strategy_lab_simple_v5 import (
    render_strategy_lab_pnl_v5 as render_strategy_lab_pnl_v1,
)
from tradingdesk_ui.charts.navigation_sync import render_tradingdesk_navigation_sync_v1
from tradingdesk_ui.charts.responsive_runtime import render_tradingdesk_responsive_runtime_v1


def render_tradingdesk_automanage_panel_v2(
    context: TradingDeskV2Context,
    *, auto_refresh: bool = True,
) -> tuple | None:
    """Render interactive Simple Core controls in their own rerun domain."""
    render_tradingdesk_responsive_runtime_v1()
    render_tradingdesk_navigation_sync_v1()

    @st.fragment(run_every="10s" if auto_refresh else None)
    def _automanager_fragment_v2():
        observations = render_tradingdesk_automanager_simple_v1(context)
        selected_account = st.session_state.get(f"td-active-account:{context.market_id}")
        render_close_position_control_v1(context, observations=observations, account_id=selected_account)
        render_tradingdesk_chart_trade_controls_v1(context, observations=observations, account_id=selected_account)
        render_tradingdesk_pilot_status_panel_v1(context, observations=observations, account_id=selected_account)
        return observations

    return _automanager_fragment_v2()


def render_tradingdesk_automanage_pnl_chart_v2(
    context: TradingDeskV2Context,
    *,
    observations: tuple | None = None,
    auto_refresh: bool = True,
    include_sim_lab: bool = True,
) -> None:
    """Render persisted benchmark strategy history with a normalized percentage chart."""

    @st.fragment(run_every="60s" if auto_refresh else None)
    def _pnl_fragment_v2() -> None:
        if not using_postgres():
            return
        try:
            enrollments, historical_fallback = pnl_enrollments_for_context_v2(context)
        except Exception as exc:
            st.caption(f"P/L-grafen venter: {exc}")
            return
        if not enrollments:
            st.caption("P/L-graf: ingen AutoManager-pilot finnes ennå for dette markedet.")
            return

        groups: dict[tuple[str, int, str, int], list] = {}
        for enrollment in enrollments:
            key = (
                enrollment.account_id,
                int(enrollment.uic),
                enrollment.asset_type,
                int(enrollment.instrument_id),
            )
            groups.setdefault(key, []).append(enrollment)

        st.divider()
        st.markdown("**P/L · benchmark og Strategy Lab**")
        if historical_fallback:
            st.caption(
                "Viser siste AutoManager-pilot som historikk. "
                "Ingen aktiv execution-authority gjenopprettes av grafen."
            )

        for key, group in groups.items():
            try:
                comparison = load_automanager_pnl_comparison_v2(tuple(group))
            except Exception as exc:
                st.caption(f"UIC {key[1]} · P/L-sammenligning venter: {exc}")
                continue

            if len(groups) > 1:
                st.caption(f"UIC {key[1]} · {key[2]}")
            render_strategy_lab_pnl_v1(
                comparison,
                key=f"td-strategy-lab-lw:{key[0]}:{key[1]}:{key[2]}:{key[3]}",
            )

            live = next(
                (item for item in group if item.execution_mode == EXECUTION_MODE_LIVE),
                None,
            )
            if live is not None and live.enabled:
                render_automanager_activity_log_v2(live, observations=observations)
            elif live is not None:
                st.caption(
                    "Denne pilotens P/L-logg er historisk; AutoManager er ikke aktivert "
                    "av denne visningen."
                )

        if include_sim_lab:
            render_tradingdesk_three_trader_lab_v1(context)
        if st.toggle(
            "Vis utvidede analyselaboratorier",
            key=f"tradingdesk-extended-labs:{context.instrument_id}",
            help="Åpner Supervisor, Scoreboard, Hybrid Lab og Storage Audit.",
        ):
            render_tradingdesk_macd_supervisor_lab_v1(context)
            render_tradingdesk_strategy_scoreboard_v1(context)
            render_tradingdesk_hybrid_lab_v1(context)
            render_tradingdesk_storage_audit_v1()

    return _pnl_fragment_v2()


__all__ = [
    "AutoManagePanelSnapshotV2",
    "render_tradingdesk_automanage_panel_v2",
    "render_tradingdesk_automanage_pnl_chart_v2",
]
