from __future__ import annotations


def test_realtime_worker_starts_risk_control() -> None:
    source = open("realtime_worker.py", encoding="utf-8").read()
    assert "run_risk_control_forever_v2" in source
    assert "PRICEGAUGER_AUTOTRADER_RISK_CONTROL_SECONDS" in source
    assert "PRICEGAUGER_AUTOTRADER_RISK_DRY_RUN_SECONDS" in source
    assert "pricegauger-autotrader-risk-control" in source


def test_autotrader_page_renders_risk_controls() -> None:
    source = open("pages/6_AutoTrader_POC.py", encoding="utf-8").read()
    assert "render_risk_control_monitor_v2" in source
    assert "WOULD_CLOSE" in source


def test_live_execution_boundary_is_unchanged() -> None:
    trading_source = open("saxo_trading.py", encoding="utf-8").read()
    risk_source = open("autotrader_risk_control_v2.py", encoding="utf-8").read()
    assert "AutoTrader er låst til Saxo SIM" in trading_source
    assert "place_order(" not in risk_source
    assert "trade/v2/orders" not in risk_source
