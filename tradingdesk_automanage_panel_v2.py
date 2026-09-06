from __future__ import annotations

# Transitional facade: keep the persisted P/L/read-model implementation stable while
# replacing the old confirmation-heavy control plane with Simple Core v1.
import streamlit as st

from trading_desk_v2_context import TradingDeskV2Context
from tradingdesk_automanage_panel_legacy_v2 import (
    AutoManagePanelSnapshotV2,
    render_tradingdesk_automanage_pnl_chart_v2,
)
from tradingdesk_automanager_simple_v1 import render_tradingdesk_automanager_simple_v1
from tradingdesk_ui.charts.interaction_capture_v2 import render_tradingdesk_interaction_capture_v2
from tradingdesk_ui.charts.navigation_sync import render_tradingdesk_navigation_sync_v1
from tradingdesk_ui.charts.responsive_runtime import render_tradingdesk_responsive_runtime_v1


def render_tradingdesk_automanage_panel_v2(
    context: TradingDeskV2Context,
) -> tuple | None:
    """Render interactive Simple Core controls in their own rerun domain."""

    # Transitional mount point for the new TradingDesk presentation boundary.
    # These runtimes are browser/UI-only and intentionally sit outside
    # AutoManager strategy/execution authority.
    render_tradingdesk_responsive_runtime_v1()
    render_tradingdesk_navigation_sync_v1()
    render_tradingdesk_interaction_capture_v2()

    @st.fragment
    def _automanager_fragment_v2():
        return render_tradingdesk_automanager_simple_v1(context)

    return _automanager_fragment_v2()


__all__ = [
    "AutoManagePanelSnapshotV2",
    "render_tradingdesk_automanage_panel_v2",
    "render_tradingdesk_automanage_pnl_chart_v2",
]
