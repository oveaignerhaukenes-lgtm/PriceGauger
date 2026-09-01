from __future__ import annotations

from pathlib import Path


def test_mtf_short_runtime_emits_requests_but_has_no_saxo_post_authority() -> None:
    source = Path("autotrader_mtf_short_live_runtime_v2.py").read_text(encoding="utf-8")
    assert "pg_v2_autotrader_execution_requests" in source
    assert "desired_direction" in source
    assert 'return "OPEN" if observed_direction == "FLAT" else None' in source
    assert 'return "CLOSE" if observed_direction == "SHORT" else None' in source
    assert "BOOTSTRAP_NO_REPLAY" in source
    assert "NEWER_MTF_SHORT_SIGNAL" in source
    assert "_post_once" not in source
    assert "trade/v2/orders" not in source
    assert "live_open_order_payload_v2" not in source


def test_mtf_short_uses_separate_runtime_state_and_refuses_long_adoption() -> None:
    source = Path("autotrader_mtf_short_live_runtime_v2.py").read_text(encoding="utf-8")
    assert "pg_v2_autotrader_mtf_short_live_state" in source
    assert "pg_v2_autotrader_mtf_short_live_events" in source
    assert "MTF short/flat cannot bootstrap from a LONG position" in source
    assert "MTF short/flat cannot manage an observed LONG exposure" in source


def test_dispatch_selects_mtf_short_and_worker_uses_dispatch_forever_loop() -> None:
    dispatch = Path("autotrader_automanage_dispatch_v2.py").read_text(encoding="utf-8")
    worker = Path("realtime_worker.py").read_text(encoding="utf-8")
    assert "MTF_SHORT_FLAT_STRATEGY_V2" in dispatch
    assert "run_mtf_short_live_strategy_once_v2" in dispatch
    assert "from autotrader_automanage_dispatch_v2 import run_automanage_strategy_forever_v2" in worker
    assert "from autotrader_automanage_runtime_v2 import run_automanage_strategy_forever_v2" not in worker
