from __future__ import annotations

from pathlib import Path

from consumer_cutover_manifest_v2 import (
    CONSUMER_CUTOVER_V2,
    CUTOVER,
    MIXED_SURFACE,
    RETIRE,
    TEMPORARY_ADAPTER,
)


AUTHORITATIVE_CONSUMERS = (
    "live_technical_runtime_v2.py",
    "parallel_forecast_runtime_v2.py",
    "autotrader_macd_dry_run_v2.py",
    "pages/0_TradingDesk.py",
)

FORBIDDEN_DIRECT_LEGACY_READS = (
    "FROM realtime_bars_1m",
    "FROM technical_market_state_snapshots",
    "FROM decision_state",
    "FROM recommendation_state",
)


def test_manifest_uses_explicit_migration_classifications():
    allowed = {CUTOVER, TEMPORARY_ADAPTER, RETIRE, MIXED_SURFACE}
    assert CONSUMER_CUTOVER_V2
    assert all(item.classification in allowed for item in CONSUMER_CUTOVER_V2)
    assert any(item.classification == TEMPORARY_ADAPTER for item in CONSUMER_CUTOVER_V2)
    assert any(item.classification == RETIRE for item in CONSUMER_CUTOVER_V2)


def test_authoritative_consumers_do_not_read_legacy_tables_directly():
    for path in AUTHORITATIVE_CONSUMERS:
        source = Path(path).read_text(encoding="utf-8")
        for token in FORBIDDEN_DIRECT_LEGACY_READS:
            assert token not in source, f"{path} bypasses the v2/adapter boundary with {token!r}"


def test_authoritative_history_consumers_share_market_history_contract():
    for path in (
        "live_technical_runtime_v2.py",
        "parallel_forecast_runtime_v2.py",
        "autotrader_macd_dry_run_v2.py",
    ):
        source = Path(path).read_text(encoding="utf-8")
        assert "MarketHistoryStore" in source


def test_trading_desk_has_no_hidden_legacy_analysis_fallback():
    source = Path("pages/0_TradingDesk.py").read_text(encoding="utf-8")
    assert "load_trading_desk_contexts_v2" in source
    assert "Legacy analyse/forecast brukes ikke som skjult fallback" in source


def test_legacy_bar_reads_are_confined_to_named_compatibility_adapter():
    source = Path("market_history_store.py").read_text(encoding="utf-8")
    assert "_legacy_realtime_range" in source
    assert "_v2_range" in source
    assert source.index("_legacy_realtime_range") < source.index("_v2_range")
