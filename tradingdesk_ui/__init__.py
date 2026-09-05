"""TradingDesk presentation boundary.

This package is the migration target for TradingDesk UI composition, responsive
layout, chart presentation, and presentation-only adapters. Execution authority,
strategy policy, Saxo order handling, risk controls, and sizing remain outside this
boundary.
"""

from tradingdesk_ui.layout.responsive import (
    TRADINGDESK_ANALYSIS_SECTION_KEY,
    TRADINGDESK_AUTOMANAGER_SECTION_KEY,
    TRADINGDESK_CONTROLS_WIDTH_SETTING_KEY,
    TRADINGDESK_LIVE_SECTION_KEY,
    TRADINGDESK_RESPONSIVE_SHELL_KEY,
    render_tradingdesk_responsive_foundation_v1,
    tradingdesk_responsive_columns_v1,
)

__all__ = [
    "TRADINGDESK_ANALYSIS_SECTION_KEY",
    "TRADINGDESK_AUTOMANAGER_SECTION_KEY",
    "TRADINGDESK_CONTROLS_WIDTH_SETTING_KEY",
    "TRADINGDESK_LIVE_SECTION_KEY",
    "TRADINGDESK_RESPONSIVE_SHELL_KEY",
    "render_tradingdesk_responsive_foundation_v1",
    "tradingdesk_responsive_columns_v1",
]
