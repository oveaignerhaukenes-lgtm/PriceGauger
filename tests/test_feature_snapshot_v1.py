from __future__ import annotations

from pathlib import Path

from feature_snapshot_v1 import (
    AGGREGATE_TIMEFRAME,
    FEATURE_SET_V1,
    FEATURE_SET_VERSION_V1,
    feature_snapshot_identity_v1,
    feature_values_v1,
    normalized_feature_payload_v1,
)
from technical_core_v2 import TechnicalCoreState


ROOT = Path(__file__).resolve().parents[1]


def _state() -> TechnicalCoreState:
    common = {
        "asset": "US Tech 100",
        "price": 29466.0,
        "rsi_14": 61.5,
        "rsi_change_3": 3.2,
        "macd": 12.0,
        "macd_signal": 8.0,
        "macd_histogram": 4.0,
        "macd_histogram_change_3": 1.5,
        "ema_20": 29420.0,
        "ema_50": 29370.0,
        "atr_14": 18.0,
        "atr_14_pct": 0.061,
        "volume_ratio_20": 1.4,
        "support": 29380.0,
        "resistance": 29510.0,
        "distance_to_support_pct": 0.29,
        "distance_to_resistance_pct": 0.15,
        "market_structure": "HH_HL",
        "price_to_ema20_pct": 0.16,
        "price_to_ema50_pct": 0.33,
        "recent_return_3_pct": 0.22,
        "recent_return_8_pct": 0.45,
        "readings": [],
    }
    one = dict(common)
    one.update({"timeframe": "1m", "timestamp": "2026-09-03T21:24:00+00:00"})
    five = dict(common)
    five.update({"timeframe": "5m", "timestamp": "2026-09-03T21:20:00+00:00", "rsi_14": 57.0})
    return TechnicalCoreState(
        market="US Tech 100",
        as_of="2026-09-03T21:00:00+00:00",
        recipe_version="technical-core-v2.1",
        primary_timeframe="30m",
        trend_state="BULLISH",
        momentum_state="BULLISH",
        volatility_state="LOW",
        structure_state="HH_HL",
        score=0.42,
        confidence=0.78,
        snapshots={"1m": one, "5m": five},
    )


def test_feature_snapshot_identity_is_stable_and_versioned() -> None:
    first = feature_snapshot_identity_v1(
        instrument_id=91,
        as_of="2026-09-03T21:24:00Z",
    )
    second = feature_snapshot_identity_v1(
        instrument_id=91,
        as_of="2026-09-03T21:24:00+00:00",
    )
    changed = feature_snapshot_identity_v1(
        instrument_id=91,
        as_of="2026-09-03T21:24:00+00:00",
        feature_set_version=FEATURE_SET_VERSION_V1 + 1,
    )
    assert first == second
    assert first != changed


def test_normalized_payload_uses_shared_namespaces_across_timeframes() -> None:
    payload = normalized_feature_payload_v1(_state())
    assert payload["schema"] == "pg-feature-snapshot-v1"
    assert payload["feature_set"] == FEATURE_SET_V1
    assert payload["feature_set_version"] == FEATURE_SET_VERSION_V1
    assert payload["aggregate"]["trend_state"] == "BULLISH"
    assert payload["timeframes"]["1m"]["momentum"]["macd"]["histogram"] == 4.0
    assert payload["timeframes"]["5m"]["momentum"]["rsi_14"] == 57.0
    assert payload["timeframes"]["1m"]["structure"]["state"] == "HH_HL"
    assert "readings" not in payload["timeframes"]["1m"]


def test_long_form_values_make_features_directly_comparable() -> None:
    values = feature_values_v1(_state())
    lookup = {(item.timeframe, item.feature_name): item for item in values}
    assert lookup[(AGGREGATE_TIMEFRAME, "state.score")].numeric_value == 0.42
    assert lookup[(AGGREGATE_TIMEFRAME, "state.trend")].text_value == "BULLISH"
    assert lookup[("1m", "momentum.macd.histogram")].numeric_value == 4.0
    assert lookup[("5m", "momentum.rsi_14")].numeric_value == 57.0
    assert lookup[("1m", "structure.state")].text_value == "HH_HL"


def test_v2_schema_contains_immutable_snapshot_spine_and_analysis_projection() -> None:
    schema = (ROOT / "db_v2_schema.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS pg_v2_feature_snapshots" in schema
    assert "UNIQUE(instrument_id, as_of, feature_set, feature_set_version)" in schema
    assert "CREATE TABLE IF NOT EXISTS pg_v2_feature_values" in schema
    assert "PRIMARY KEY (feature_snapshot_id, timeframe, feature_name)" in schema
    assert "features_json JSONB" in schema


def test_live_technical_runtime_persists_snapshot_after_technical_state() -> None:
    source = (ROOT / "live_technical_runtime_v2.py").read_text(encoding="utf-8")
    persist_runtime = source.index("persist_produced_runtime_v2(")
    persist_snapshot = source.index("persist_feature_snapshot_v1(")
    assert persist_runtime < persist_snapshot
    assert "technical_state_identity_v2(" in source
    assert "instrument_source.instrument_id" in source
