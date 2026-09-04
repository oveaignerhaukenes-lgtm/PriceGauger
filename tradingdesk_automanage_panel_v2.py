from __future__ import annotations

# Transitional facade: keep the persisted P/L/read-model implementation stable while
# replacing the old confirmation-heavy control plane with Simple Core v1.
from tradingdesk_automanage_panel_legacy_v2 import (
    AutoManagePanelSnapshotV2,
    render_tradingdesk_automanage_pnl_chart_v2,
)
from tradingdesk_automanager_simple_v1 import (
    render_tradingdesk_automanager_simple_v1 as render_tradingdesk_automanage_panel_v2,
)


__all__ = [
    "AutoManagePanelSnapshotV2",
    "render_tradingdesk_automanage_panel_v2",
    "render_tradingdesk_automanage_pnl_chart_v2",
]
