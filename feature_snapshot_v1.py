from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import UUID, uuid5

from database import connect
from technical_core_v2 import TechnicalCoreState


FEATURE_SNAPSHOT_NAMESPACE_V1 = UUID("96ed4f7e-413a-4c10-8acb-64e5e22dba79")
FEATURE_SET_V1 = "technical-core-normalized"
FEATURE_SET_VERSION_V1 = 1
AGGREGATE_TIMEFRAME = "aggregate"


@dataclass(frozen=True, slots=True)
class FeatureValueV1:
    timeframe: str
    feature_name: str
    numeric_value: float | None = None
    text_value: str | None = None


@dataclass(frozen=True, slots=True)
class FeaturePointV1:
    as_of: datetime
    timeframe: str
    feature_name: str
    numeric_value: float | None
    text_value: str | None


_NUMERIC_FIELDS: tuple[tuple[str, str], ...] = (
    ("price.close", "price"),
    ("momentum.rsi_14", "rsi_14"),
    ("momentum.rsi_change_3", "rsi_change_3"),
    ("momentum.macd.line", "macd"),
    ("momentum.macd.signal", "macd_signal"),
    ("momentum.macd.histogram", "macd_histogram"),
    ("momentum.macd.histogram_change_3", "macd_histogram_change_3"),
    ("trend.ema_20", "ema_20"),
    ("trend.ema_50", "ema_50"),
    ("trend.price_to_ema20_pct", "price_to_ema20_pct"),
    ("trend.price_to_ema50_pct", "price_to_ema50_pct"),
    ("volatility.atr_14", "atr_14"),
    ("volatility.atr_14_pct", "atr_14_pct"),
    ("activity.volume_ratio_20", "volume_ratio_20"),
    ("levels.support", "support"),
    ("levels.resistance", "resistance"),
    ("levels.distance_to_support_pct", "distance_to_support_pct"),
    ("levels.distance_to_resistance_pct", "distance_to_resistance_pct"),
    ("returns.recent_3_pct", "recent_return_3_pct"),
    ("returns.recent_8_pct", "recent_return_8_pct"),
)


def _utc(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _json_placeholder(db) -> str:
    return "?::jsonb" if db.is_postgres else "?"


def _row_dict(row: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    if isinstance(row, dict):
        return dict(row)
    return {key: row[index] for index, key in enumerate(keys)}


def feature_snapshot_identity_v1(
    *,
    instrument_id: int,
    as_of: datetime | str,
    feature_set: str = FEATURE_SET_V1,
    feature_set_version: int = FEATURE_SET_VERSION_V1,
) -> UUID:
    timestamp = _utc(as_of).isoformat()
    return uuid5(
        FEATURE_SNAPSHOT_NAMESPACE_V1,
        f"feature-snapshot:{int(instrument_id)}:{timestamp}:{feature_set}:{int(feature_set_version)}",
    )


def _feature_as_of(state: TechnicalCoreState) -> datetime:
    preferred = state.snapshots.get("1m")
    if preferred and preferred.get("timestamp"):
        return _utc(preferred["timestamp"])
    timestamps = [
        _utc(snapshot["timestamp"])
        for snapshot in state.snapshots.values()
        if snapshot.get("timestamp")
    ]
    if timestamps:
        return max(timestamps)
    return _utc(state.as_of)


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result


def _normalized_timeframe(snapshot: dict[str, Any]) -> dict[str, Any]:
    macd = {
        "line": _float_or_none(snapshot.get("macd")),
        "signal": _float_or_none(snapshot.get("macd_signal")),
        "histogram": _float_or_none(snapshot.get("macd_histogram")),
        "histogram_change_3": _float_or_none(snapshot.get("macd_histogram_change_3")),
    }
    return {
        "as_of": snapshot.get("timestamp"),
        "price": {"close": _float_or_none(snapshot.get("price"))},
        "returns": {
            "recent_3_pct": _float_or_none(snapshot.get("recent_return_3_pct")),
            "recent_8_pct": _float_or_none(snapshot.get("recent_return_8_pct")),
        },
        "momentum": {
            "rsi_14": _float_or_none(snapshot.get("rsi_14")),
            "rsi_change_3": _float_or_none(snapshot.get("rsi_change_3")),
            "macd": macd,
        },
        "trend": {
            "ema_20": _float_or_none(snapshot.get("ema_20")),
            "ema_50": _float_or_none(snapshot.get("ema_50")),
            "price_to_ema20_pct": _float_or_none(snapshot.get("price_to_ema20_pct")),
            "price_to_ema50_pct": _float_or_none(snapshot.get("price_to_ema50_pct")),
        },
        "volatility": {
            "atr_14": _float_or_none(snapshot.get("atr_14")),
            "atr_14_pct": _float_or_none(snapshot.get("atr_14_pct")),
        },
        "activity": {"volume_ratio_20": _float_or_none(snapshot.get("volume_ratio_20"))},
        "levels": {
            "support": _float_or_none(snapshot.get("support")),
            "resistance": _float_or_none(snapshot.get("resistance")),
            "distance_to_support_pct": _float_or_none(snapshot.get("distance_to_support_pct")),
            "distance_to_resistance_pct": _float_or_none(snapshot.get("distance_to_resistance_pct")),
        },
        "structure": {"state": str(snapshot.get("market_structure") or "UNDETERMINED")},
    }


def normalized_feature_payload_v1(state: TechnicalCoreState) -> dict[str, Any]:
    return {
        "schema": "pg-feature-snapshot-v1",
        "feature_set": FEATURE_SET_V1,
        "feature_set_version": FEATURE_SET_VERSION_V1,
        "market": state.market,
        "aggregate": {
            "primary_timeframe": state.primary_timeframe,
            "trend_state": state.trend_state,
            "momentum_state": state.momentum_state,
            "volatility_state": state.volatility_state,
            "structure_state": state.structure_state,
            "score": float(state.score),
            "confidence": float(state.confidence),
            "technical_recipe_version": state.recipe_version,
        },
        "timeframes": {
            timeframe: _normalized_timeframe(dict(snapshot))
            for timeframe, snapshot in sorted(state.snapshots.items())
        },
        "data_quality": {
            "status": "OBSERVED",
            "source": "canonical-1m-resample",
            "note": "Snapshot is immutable; explicit gap/freshness features may be added in a later feature-set version.",
        },
    }


def feature_values_v1(state: TechnicalCoreState) -> tuple[FeatureValueV1, ...]:
    values: list[FeatureValueV1] = [
        FeatureValueV1(AGGREGATE_TIMEFRAME, "state.score", numeric_value=float(state.score)),
        FeatureValueV1(AGGREGATE_TIMEFRAME, "state.confidence", numeric_value=float(state.confidence)),
        FeatureValueV1(AGGREGATE_TIMEFRAME, "state.primary_timeframe", text_value=state.primary_timeframe),
        FeatureValueV1(AGGREGATE_TIMEFRAME, "state.trend", text_value=state.trend_state),
        FeatureValueV1(AGGREGATE_TIMEFRAME, "state.momentum", text_value=state.momentum_state),
        FeatureValueV1(AGGREGATE_TIMEFRAME, "state.volatility", text_value=state.volatility_state),
        FeatureValueV1(AGGREGATE_TIMEFRAME, "state.structure", text_value=state.structure_state),
    ]
    for timeframe, snapshot in sorted(state.snapshots.items()):
        raw = dict(snapshot)
        for feature_name, source_name in _NUMERIC_FIELDS:
            numeric = _float_or_none(raw.get(source_name))
            if numeric is not None:
                values.append(FeatureValueV1(timeframe, feature_name, numeric_value=numeric))
        values.append(
            FeatureValueV1(
                timeframe,
                "structure.state",
                text_value=str(raw.get("market_structure") or "UNDETERMINED"),
            )
        )
    return tuple(values)


def persist_feature_snapshot_v1(
    *,
    market_id: int,
    instrument_id: int,
    state: TechnicalCoreState,
    source_technical_state_id: UUID | str | None,
) -> UUID:
    as_of = _feature_as_of(state)
    snapshot_id = feature_snapshot_identity_v1(instrument_id=instrument_id, as_of=as_of)
    payload = normalized_feature_payload_v1(state)
    values = feature_values_v1(state)
    with connect() as db:
        json_value = _json_placeholder(db)
        db.execute(
            f"""
            INSERT INTO pg_v2_feature_snapshots(
                feature_snapshot_id, market_id, instrument_id, as_of,
                feature_set, feature_set_version, source_technical_state_id,
                primary_timeframe, trend_state, momentum_state, volatility_state,
                structure_state, score, confidence, data_quality, features_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, {json_value})
            ON CONFLICT (instrument_id, as_of, feature_set, feature_set_version) DO NOTHING
            """,
            (
                str(snapshot_id), int(market_id), int(instrument_id), as_of,
                FEATURE_SET_V1, FEATURE_SET_VERSION_V1,
                None if source_technical_state_id is None else str(source_technical_state_id),
                state.primary_timeframe, state.trend_state, state.momentum_state,
                state.volatility_state, state.structure_state, float(state.score),
                float(state.confidence), "OBSERVED", _json(payload),
            ),
        )
        for item in values:
            db.execute(
                """
                INSERT INTO pg_v2_feature_values(
                    feature_snapshot_id, timeframe, feature_name, numeric_value, text_value
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (feature_snapshot_id, timeframe, feature_name) DO NOTHING
                """,
                (
                    str(snapshot_id), item.timeframe, item.feature_name,
                    item.numeric_value, item.text_value,
                ),
            )
    return snapshot_id


def load_feature_series_v1(
    *,
    instrument_id: int,
    timeframe: str,
    feature_name: str,
    start: datetime | None = None,
    end: datetime | None = None,
    feature_set: str = FEATURE_SET_V1,
    feature_set_version: int = FEATURE_SET_VERSION_V1,
) -> tuple[FeaturePointV1, ...]:
    clauses = [
        "snap.instrument_id = ?",
        "snap.feature_set = ?",
        "snap.feature_set_version = ?",
        "value.timeframe = ?",
        "value.feature_name = ?",
    ]
    params: list[Any] = [
        int(instrument_id), feature_set, int(feature_set_version), timeframe, feature_name,
    ]
    if start is not None:
        clauses.append("snap.as_of >= ?")
        params.append(_utc(start))
    if end is not None:
        clauses.append("snap.as_of <= ?")
        params.append(_utc(end))
    with connect() as db:
        rows = db.execute(
            f"""
            SELECT snap.as_of, value.timeframe, value.feature_name,
                   value.numeric_value, value.text_value
            FROM pg_v2_feature_snapshots AS snap
            JOIN pg_v2_feature_values AS value
              ON value.feature_snapshot_id = snap.feature_snapshot_id
            WHERE {' AND '.join(clauses)}
            ORDER BY snap.as_of ASC
            """,
            tuple(params),
        ).fetchall()
    points: list[FeaturePointV1] = []
    keys = ("as_of", "timeframe", "feature_name", "numeric_value", "text_value")
    for row in rows:
        item = _row_dict(row, keys)
        points.append(
            FeaturePointV1(
                as_of=_utc(item["as_of"]),
                timeframe=str(item["timeframe"]),
                feature_name=str(item["feature_name"]),
                numeric_value=None if item["numeric_value"] is None else float(item["numeric_value"]),
                text_value=None if item["text_value"] is None else str(item["text_value"]),
            )
        )
    return tuple(points)


def load_latest_feature_snapshot_v1(
    *,
    instrument_id: int,
    feature_set: str = FEATURE_SET_V1,
    feature_set_version: int = FEATURE_SET_VERSION_V1,
) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute(
            """
            SELECT as_of, features_json
            FROM pg_v2_feature_snapshots
            WHERE instrument_id = ? AND feature_set = ? AND feature_set_version = ?
            ORDER BY as_of DESC
            LIMIT 1
            """,
            (int(instrument_id), feature_set, int(feature_set_version)),
        ).fetchone()
    if row is None:
        return None
    values = _row_dict(row, ("as_of", "features_json"))
    raw = values["features_json"]
    payload = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
    payload["as_of"] = _utc(values["as_of"]).isoformat()
    return payload


__all__ = [
    "AGGREGATE_TIMEFRAME",
    "FEATURE_SET_V1",
    "FEATURE_SET_VERSION_V1",
    "FeaturePointV1",
    "FeatureValueV1",
    "feature_snapshot_identity_v1",
    "feature_values_v1",
    "load_feature_series_v1",
    "load_latest_feature_snapshot_v1",
    "normalized_feature_payload_v1",
    "persist_feature_snapshot_v1",
]
