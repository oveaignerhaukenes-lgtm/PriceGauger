from __future__ import annotations

from pathlib import Path

from tradingdesk_ui.charts.profile import RESPONSIVE_CHART_PROFILE_V1
from tradingdesk_ui.layout.responsive import MOBILE_BREAKPOINT_PX


def test_tradingdesk_mobile_profile_reclaims_desktop_chart_rail() -> None:
    profile = RESPONSIVE_CHART_PROFILE_V1
    assert MOBILE_BREAKPOINT_PX == 760
    assert profile.mobile_breakpoint_px == MOBILE_BREAKPOINT_PX
    assert profile.mobile_right_margin_px <= 20
    assert profile.mobile_bottom_margin_live_px >= 200
    assert profile.mobile_bottom_margin_strategy_px >= profile.mobile_bottom_margin_live_px
    assert profile.mobile_height_extra_px >= 120


def test_responsive_layout_stacks_streamlit_columns_only_when_narrow() -> None:
    source = Path("tradingdesk_ui/layout/responsive.py").read_text(encoding="utf-8")
    assert "@media (max-width:" in source
    assert '.block-container div[data-testid="stHorizontalBlock"]' in source
    assert "flex-direction: column !important" in source
    assert '.block-container div[data-testid="stPlotlyChart"]' in source


def test_responsive_chart_runtime_handles_live_and_strategy_charts() -> None:
    source = Path("tradingdesk_ui/charts/responsive_runtime.py").read_text(encoding="utf-8")
    assert "TradingDesk:" in source
    assert "AutoManagerPnlProduct:" in source
    assert "ResizeObserver" in source
    assert "mobileUpdates" in source
    assert "positionInspector" in source
    assert "legend.orientation" in source
    assert "margin.r" in source


def test_responsive_ui_boundary_has_no_execution_authority() -> None:
    root = Path("tradingdesk_ui")
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in root.rglob("*.py")
    )
    forbidden = (
        "SaxoOrder",
        "place_order",
        "submit_order",
        "autotrader_live_open",
        "autotrader_live_close",
        "ProductAdmission",
        "PositionGuardian",
    )
    for token in forbidden:
        assert token not in source


def test_transitional_facade_mounts_responsive_runtime_without_moving_execution() -> None:
    source = Path("tradingdesk_automanage_panel_v2.py").read_text(encoding="utf-8")
    assert "tradingdesk_ui.charts.responsive_runtime" in source
    assert "render_tradingdesk_responsive_runtime_v1()" in source
    assert "render_tradingdesk_automanager_simple_v1(context)" in source
