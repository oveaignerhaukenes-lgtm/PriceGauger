from __future__ import annotations

from pathlib import Path


def test_shadow_benchmark_has_no_execution_or_authoritative_pnl_authority():
    source = Path("autotrader_shadow_benchmark_v2.py").read_text(encoding="utf-8")
    forbidden = (
        "record_realized_net_pnl_v2",
        "pg_v2_autotrader_pilot_equity_events",
        "pg_v2_autotrader_live_open_attempts",
        "pg_v2_autotrader_live_close_attempts",
        "session.post",
        "_post_once",
        "CREATE TABLE",
        "INSERT INTO",
        "UPDATE pg_v2",
        "DELETE FROM",
    )
    for token in forbidden:
        assert token not in source
