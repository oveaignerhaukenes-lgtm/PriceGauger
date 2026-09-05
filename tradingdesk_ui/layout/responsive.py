from __future__ import annotations

import streamlit as st


MOBILE_BREAKPOINT_PX = 760
TRADINGDESK_RESPONSIVE_SHELL_KEY = "tradingdesk_responsive_shell_v1"
TRADINGDESK_LIVE_SECTION_KEY = "tradingdesk_live_section_v1"
TRADINGDESK_AUTOMANAGER_SECTION_KEY = "tradingdesk_automanager_section_v1"
TRADINGDESK_ANALYSIS_SECTION_KEY = "tradingdesk_analysis_section_v1"
TRADINGDESK_CONTROLS_WIDTH_SETTING_KEY = "tradingdesk_controls_width_setting_v1"


_DESKTOP_AND_RESPONSIVE_CSS = f"""
<style>
div[data-testid="stMainBlockContainer"], .block-container {{
    max-width: 100% !important;
    padding-left: 1.25rem !important;
    padding-right: 1.25rem !important;
}}
div[data-testid="stPlotlyChart"] .modebar {{
    top: .35rem !important;
    right: .35rem !important;
    flex-direction: row !important;
    background: rgba(255,255,255,.94) !important;
    border: 1px solid rgba(17,24,39,.16) !important;
    border-radius: .45rem !important;
    padding: .18rem !important;
}}
div[data-testid="stPlotlyChart"] .modebar-group {{
    display: flex !important;
    flex-direction: row !important;
}}

@media (max-width: {MOBILE_BREAKPOINT_PX}px) {{
    div[data-testid="stMainBlockContainer"], .block-container {{
        padding-left: .55rem !important;
        padding-right: .55rem !important;
        padding-top: .55rem !important;
    }}

    /* TradingDesk deliberately becomes a single-column cockpit on narrow screens.
       The CSS is injected only by TradingDesk, so this does not alter other pages. */
    .block-container div[data-testid="stHorizontalBlock"] {{
        flex-direction: column !important;
        flex-wrap: nowrap !important;
        gap: .55rem !important;
    }}
    .block-container div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {{
        width: 100% !important;
        min-width: 0 !important;
        flex: 1 1 100% !important;
    }}

    .st-key-{TRADINGDESK_LIVE_SECTION_KEY} {{ order: 1 !important; }}
    .st-key-{TRADINGDESK_AUTOMANAGER_SECTION_KEY} {{ order: 2 !important; }}
    .st-key-{TRADINGDESK_ANALYSIS_SECTION_KEY} {{ order: 3 !important; }}
    .st-key-{TRADINGDESK_CONTROLS_WIDTH_SETTING_KEY} {{ display: none !important; }}

    .block-container div[data-testid="stPlotlyChart"],
    .block-container div[data-testid="stPlotlyChart"] > div {{
        width: 100% !important;
        min-width: 0 !important;
    }}

    .block-container button,
    .block-container [data-testid="stBaseButton-secondary"],
    .block-container [data-testid="stBaseButton-primary"] {{
        min-height: 2.6rem;
    }}

    .block-container [data-testid="stMetric"] {{
        min-width: 0 !important;
    }}

    div[data-testid="stPlotlyChart"] .modebar {{
        top: .2rem !important;
        right: .2rem !important;
        transform: scale(.90);
        transform-origin: top right;
    }}
}}
</style>
"""


def render_tradingdesk_responsive_foundation_v1() -> None:
    """Install TradingDesk presentation CSS for desktop and narrow screens.

    This function is presentation-only. It does not inspect or mutate trading state,
    execution authority, strategy enrollment, sizing, or Saxo identity.
    """

    st.markdown(_DESKTOP_AND_RESPONSIVE_CSS, unsafe_allow_html=True)


def tradingdesk_responsive_columns_v1(*, controls_width_pct: int):
    """Create the desktop split inside a responsive shell for the next migration step.

    The current page still owns composition. New TradingDesk components should use this
    helper as they move into the package so desktop/mobile share one application state.
    """

    controls = max(20, min(40, int(controls_width_pct)))
    with st.container(key=TRADINGDESK_RESPONSIVE_SHELL_KEY):
        return st.columns([100 - controls, controls], gap="medium")


__all__ = [
    "MOBILE_BREAKPOINT_PX",
    "TRADINGDESK_ANALYSIS_SECTION_KEY",
    "TRADINGDESK_AUTOMANAGER_SECTION_KEY",
    "TRADINGDESK_CONTROLS_WIDTH_SETTING_KEY",
    "TRADINGDESK_LIVE_SECTION_KEY",
    "TRADINGDESK_RESPONSIVE_SHELL_KEY",
    "render_tradingdesk_responsive_foundation_v1",
    "tradingdesk_responsive_columns_v1",
]
