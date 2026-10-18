"""Shared read-only snapshot adapter for Live Chart and TradingDesk.

See live_chart_history_cache_v1 for the bounded cache and 1-second tail path.
This wrapper keeps the existing public import stable.
"""

from tradingdesk_ui.charts.lightweight.live_chart_history_cache_v1 import load_live_test_snapshot_v1

__all__ = ["load_live_test_snapshot_v1"]
