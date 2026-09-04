from __future__ import annotations


def test_realtime_worker_wires_live_close_runtime() -> None:
    source = open("realtime_worker.py", encoding="utf-8").read()
    assert "run_live_close_forever_v1" in source
    assert "_start_autotrader_live_close" in source
    assert "PRICEGAUGER_AUTOTRADER_LIVE_CLOSE_SECONDS" in source


def test_realtime_worker_wires_authoritative_pnl_reconciliation() -> None:
    source = open("realtime_worker.py", encoding="utf-8").read()
    assert "run_closed_position_equity_reconciliation_forever_v2" in source
    assert "_start_autotrader_equity_reconciliation" in source
    assert "PRICEGAUGER_AUTOTRADER_EQUITY_RECONCILIATION_SECONDS" in source


def test_autotrader_page_exposes_live_close_through_simple_core_without_user_arm_gate() -> None:
    page_source = open("pages/6_AutoTrader_POC.py", encoding="utf-8").read()
    facade_source = open("tradingdesk_automanage_panel_v2.py", encoding="utf-8").read()
    simple_source = open("tradingdesk_automanager_simple_v1.py", encoding="utf-8").read()

    assert "render_tradingdesk_automanage_panel_v2(context)" in page_source
    assert "render_tradingdesk_automanager_simple_v1" in facade_source
    assert "save_live_close_config_v1" in simple_source
    assert "LiveCloseConfigV1(armed=True)" in simple_source
    assert "def _ensure_execution_ready_v1" in simple_source
    assert "Arm automatisk LIVE CLOSE" not in simple_source
