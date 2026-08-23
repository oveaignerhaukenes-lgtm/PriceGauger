from __future__ import annotations


def test_realtime_worker_wires_live_close_runtime() -> None:
    source = open("realtime_worker.py", encoding="utf-8").read()
    assert "run_live_close_forever_v1" in source
    assert "_start_autotrader_live_close" in source
    assert "PRICEGAUGER_AUTOTRADER_LIVE_CLOSE_SECONDS" in source


def test_autotrader_page_exposes_live_close_controls() -> None:
    source = open("pages/6_AutoTrader_POC.py", encoding="utf-8").read()
    assert "render_live_close_v1" in source
    assert "LIVE close-only" in source
