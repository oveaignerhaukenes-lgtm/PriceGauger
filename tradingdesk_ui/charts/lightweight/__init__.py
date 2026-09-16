"""TradingDesk Lightweight Charts presentation boundary.

This package owns browser rendering and presentation-only data contracts. It has no
strategy, risk, sizing, Product Admission, Saxo order, or execution authority.
"""

from .contract import build_lightweight_live_payload_v1
from .renderer import render_lightweight_live_chart_v1

# Streamlit component-v2 compatibility: importing any lightweight chart module first
# executes this package initializer. Patch only the presentation updater so existing
# call sites keep their stable API while changed forming candles remount the hidden
# updater component and re-run its browser-side update code.
from . import live_update as _live_update
from .live_update_refresh_v2 import render_lightweight_live_update_refresh_v2

_live_update.render_lightweight_live_update_v1 = render_lightweight_live_update_refresh_v2

__all__ = ["build_lightweight_live_payload_v1", "render_lightweight_live_chart_v1"]
