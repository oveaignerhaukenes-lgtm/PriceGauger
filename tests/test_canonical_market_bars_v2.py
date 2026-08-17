from __future__ import annotations

from pathlib import Path


def test_v2_schema_has_instrument_keyed_canonical_bar_table():
    source = Path("db_v2_schema.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS pg_v2_market_bars_1m" in source
    assert "PRIMARY KEY (instrument_id, bar_time)" in source


def test_realtime_store_dual_writes_postgres_to_v2_during_cutover():
    source = Path("realtime_market_data.py").read_text(encoding="utf-8")
    assert "CanonicalMarketBarStoreV2(self.path).save_saxo_bar" in source
    assert "if using_postgres():" in source
    assert "realtime_bars_1m" in source  # compatibility row retained during AP13


def test_market_history_prefers_v2_after_legacy_sources():
    source = Path("market_history_store.py").read_text(encoding="utf-8")
    merge = source[source.index("points=self._merge_points("):source.index("return tuple((stamp.isoformat(),price) for stamp,price in points)")]
    assert merge.index("_legacy_realtime_range") < merge.index("_v2_range")
    assert "CanonicalMarketBarStoreV2" in source


def test_gap_repair_marks_backfill_quality():
    source = Path("realtime_gap_repair.py").read_text(encoding="utf-8")
    assert "QUALITY_BACKFILL" in source
    assert "quality_flags=QUALITY_BACKFILL" in source


def test_canonical_store_requires_v2_subscribed_provider_identity():
    source = Path("canonical_market_bars_v2.py").read_text(encoding="utf-8")
    assert "require_subscription=True" in source
    assert "bar UIC does not match canonical v2 source" in source
    assert "ON CONFLICT(instrument_id, bar_time) DO UPDATE" in source
