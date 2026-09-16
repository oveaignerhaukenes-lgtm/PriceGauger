"""TradingDesk Lightweight Charts presentation boundary.

This package owns browser rendering and presentation-only data contracts. It has no
strategy, risk, sizing, Product Admission, Saxo order, or execution authority.
"""

from .contract import build_lightweight_live_payload_v1
from .renderer import render_lightweight_live_chart_v1

# Presentation compatibility shims are installed at package import so the existing
# TradingDesk call sites keep stable APIs while browser rendering evolves.
from . import direct_runtime as _direct_runtime
from . import live_update as _live_update
from .direct_runtime_oslo_v2 import render_lightweight_direct_live_oslo_v2
from .live_update_refresh_v2 import render_lightweight_live_update_refresh_v2

_direct_runtime.render_lightweight_direct_live_v1 = render_lightweight_direct_live_oslo_v2
_live_update.render_lightweight_live_update_v1 = render_lightweight_live_update_refresh_v2

__all__ = ["build_lightweight_live_payload_v1", "render_lightweight_live_chart_v1"]
