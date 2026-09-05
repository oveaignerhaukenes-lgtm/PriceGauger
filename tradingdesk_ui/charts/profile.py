from __future__ import annotations

from dataclasses import asdict, dataclass

from tradingdesk_ui.layout.responsive import MOBILE_BREAKPOINT_PX


@dataclass(frozen=True, slots=True)
class ResponsiveChartProfileV1:
    mobile_breakpoint_px: int = MOBILE_BREAKPOINT_PX
    mobile_left_margin_px: int = 46
    mobile_right_margin_px: int = 16
    mobile_top_margin_px: int = 96
    mobile_bottom_margin_live_px: int = 280
    mobile_bottom_margin_strategy_px: int = 300
    mobile_height_extra_px: int = 200
    mobile_legend_maxheight: float = 0.10
    mobile_legend_font_size: int = 10
    mobile_inspector_gap_live_px: int = 105
    mobile_inspector_gap_strategy_px: int = 125


RESPONSIVE_CHART_PROFILE_V1 = ResponsiveChartProfileV1()


def responsive_chart_profile_payload_v1() -> dict[str, int | float]:
    """Return a browser-safe presentation payload for Plotly enhancement JS."""

    return dict(asdict(RESPONSIVE_CHART_PROFILE_V1))


__all__ = [
    "RESPONSIVE_CHART_PROFILE_V1",
    "ResponsiveChartProfileV1",
    "responsive_chart_profile_payload_v1",
]
