from __future__ import annotations


def test_realtime_worker_starts_risk_dry_run() -> None:
    source = open("realtime_worker.py", encoding="utf-8").read()
    assert "run_risk_dry_run_forever_v2" in source
    assert "PRICEGAUGER_AUTOTRADER_RISK_DRY_RUN_SECONDS" in source
    assert "pricegauger-autotrader-risk-dry-run" in source


def test_autotrader_page_renders_risk_controls() -> None:
    source = open("pages/6_AutoTrader_POC.py", encoding="utf-8").read()
    assert "render_risk_dry_run_monitor_v2" in source
    assert "WOULD_CLOSE" in source


def test_live_execution_boundary_is_unchanged() -> None:
    trading_source = open("saxo_trading.py", encoding="utf-8").read()
    risk_source = open("autotrader_risk_dry_run_v2.py", encoding="utf-8").read()
    assert "AutoTrader er låst til Saxo SIM" in trading_source
    assert "place_order(" not in risk_source
    assert "trade/v2/orders" not in risk_source
