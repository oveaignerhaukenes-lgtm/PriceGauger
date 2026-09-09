from __future__ import annotations

# Transitional facade: keep the persisted P/L/read-model implementation stable while
# replacing the old confirmation-heavy control plane with Simple Core v1.
import streamlit as st

from autotrader_pnl_comparison_v2 import load_automanager_pnl_comparison_v2
from autotrader_strategy_enrollment_v2 import EXECUTION_MODE_LIVE
from database import using_postgres
from trading_desk_v2_context import TradingDeskV2Context
from tradingdesk_automanage_panel_legacy_v2 import (
    AutoManagePanelSnapshotV2,
    _pnl_enrollments_for_context_v2,
    _render_automanager_activity_log_v2,
)
from tradingdesk_automanager_simple_v1 import render_tradingdesk_automanager_simple_v1
from tradingdesk_pilot_status_panel_v1 import render_tradingdesk_pilot_status_panel_v1
from tradingdesk_ui.charts.lightweight.pnl_strategy_lab_simple_v5 import (
    render_strategy_lab_pnl_v5 as render_strategy_lab_pnl_v1,
)
from tradingdesk_ui.charts.navigation_sync import render_tradingdesk_navigation_sync_v1
from tradingdesk_ui.charts.responsive_runtime import render_tradingdesk_responsive_runtime_v1


def render_tradingdesk_automanage_panel_v2(
    context: TradingDeskV2Context,
) -> tuple | None:
    """Render interactive Simple Core controls in their own rerun domain."""

    # Transitional mount point for the new TradingDesk presentation boundary.
    # LIVE chart rendering/gestures now mount with the Live Chart itself; this facade
    # keeps only shared responsive/navigation support plus AutoManager controls.
    render_tradingdesk_responsive_runtime_v1()
    render_tradingdesk_navigation_sync_v1()

    @st.fragment
    def _automanager_fragment_v2():
        observations = render_tradingdesk_automanager_simple_v1(context)
        render_tradingdesk_pilot_status_panel_v1(context, observations=observations)
        return observations

    return _automanager_fragment_v2()


def render_tradingdesk_automanage_pnl_chart_v2(
    context: TradingDeskV2Context,
    *,
    observations: tuple | None = None,
) -> None:
    """Render persisted benchmark strategy history with a normalized percentage chart."""

    @st.fragment
    def _pnl_fragment_v2() -> None:
        if not using_postgres():
            return
        try:
            enrollments, historical_fallback = _pnl_enrollments_for_context_v2(context)
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
                _render_automanager_activity_log_v2(live, observations=observations)
            elif live is not None:
                st.caption(
                    "Denne pilotens P/L-logg er historisk; AutoManager er ikke aktivert "
                    "av denne visningen."
                )

    return _pnl_fragment_v2()


__all__ = [
    "AutoManagePanelSnapshotV2",
    "render_tradingdesk_automanage_panel_v2",
    "render_tradingdesk_automanage_pnl_chart_v2",
]
