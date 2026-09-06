"""TradingDesk Lightweight Charts presentation boundary.

This package owns browser rendering and presentation-only data contracts. It has no
strategy, risk, sizing, Product Admission, Saxo order, or execution authority.
"""

from .contract import build_lightweight_live_payload_v1
from .renderer import render_lightweight_live_chart_v1

__all__ = ["build_lightweight_live_payload_v1", "render_lightweight_live_chart_v1"]
