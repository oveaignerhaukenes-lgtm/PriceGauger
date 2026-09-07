from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from database import connect
from tradingdesk_ui.charts.lightweight.pnl_comparison import _strategy_label


MANUAL_SAXO_ANOMALY_KINDS_V1 = frozenset(
    {
        "UNKNOWN_WORKING_ORDER",
        "UNEXPECTED_POSITION_ORIGIN",
    }
)


def _utc(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _epoch(value: Any) -> int:
    return int(_utc(value).timestamp())


def _live_value_at(comparison, observed_at: datetime) -> float:
    value = 0.0
    target = _utc(observed_at)
    for point in comparison.live_realized:
        if _utc(point.occurred_at) > target:
            break
        value = float(point.return_pct)
    return value


def build_live_pnl_strategy_epochs_v1(comparison) -> list[dict[str, Any]]:
    """Expose immutable LIVE strategy activation windows for chart attribution."""
    rows: list[dict[str, Any]] = []
    for epoch in comparison.live_epochs:
        rows.append(
            {
                "start": _epoch(epoch.started_at),
                "end": None if epoch.ended_at is None else _epoch(epoch.ended_at),
                "label": _strategy_label(epoch.strategy_key),
                "strategy_key": str(epoch.strategy_key),
                "pilot_key": str(epoch.pilot_key),
            }
        )
    rows.sort(key=lambda item: (int(item["start"]), str(item["pilot_key"])))
    return rows


def _manual_saxo_events(comparison) -> tuple[dict[str, Any], ...]:
    """Read only proven foreign/manual broker events already persisted by the execution guard.

    This deliberately does not infer manual intervention from price, amount, timing or
    a missing PG marker. If execution provenance cannot prove that an observed broker
    event was foreign/manual, the P/L chart stays silent rather than inventing history.
    """
    try:
        account_id, raw_uic, asset_type, _instrument_id = comparison.product_key.split(":", 3)
        with connect() as db:
            rows = db.execute(
                """
                SELECT kind, first_seen_at, external_reference, order_id, net_position_id, details
                FROM pg_v2_autotrader_execution_anomalies
                WHERE account_id = ? AND uic = ? AND asset_type = ?
                  AND kind IN ('UNKNOWN_WORKING_ORDER', 'UNEXPECTED_POSITION_ORIGIN')
                  AND first_seen_at >= ? AND first_seen_at <= ?
                ORDER BY first_seen_at ASC, anomaly_key ASC
                """,
                (
                    str(account_id),
                    int(raw_uic),
                    str(asset_type),
                    _utc(comparison.started_at),
                    _utc(comparison.as_of),
                ),
            ).fetchall()
    except Exception:
        return ()

    events: list[dict[str, Any]] = []
    for row in rows:
        values = dict(row) if isinstance(row, dict) else {
            "kind": row[0],
            "first_seen_at": row[1],
            "external_reference": row[2],
            "order_id": row[3],
            "net_position_id": row[4],
            "details": row[5],
        }
        kind = str(values.get("kind") or "")
        if kind not in MANUAL_SAXO_ANOMALY_KINDS_V1:
            continue
        observed_at = _utc(values["first_seen_at"])
        detail_parts = [
            str(values.get("external_reference") or "").strip(),
            str(values.get("order_id") or "").strip(),
            str(values.get("net_position_id") or "").strip(),
        ]
        detail = " · ".join(item for item in detail_parts if item)
        fallback = (
            "Saxo position without PG OPEN provenance"
            if kind == "UNEXPECTED_POSITION_ORIGIN"
            else "Foreign/manual Saxo working order"
        )
        events.append(
            {
                "kind": "MANUAL_SAXO",
                "source_kind": kind,
                "time": _epoch(observed_at),
                "value": _live_value_at(comparison, observed_at),
                "label": "MANUAL / SAXO",
                "detail": detail or fallback,
                "position": "aboveBar",
                "shape": "square",
                "color": "#f59e0b",
            }
        )
    return tuple(events)


def build_live_pnl_provenance_events_v1(comparison) -> list[dict[str, Any]]:
    """Build exact strategy handoff markers plus proven manual Saxo events."""
    events: list[dict[str, Any]] = []
    started = _utc(comparison.started_at)
    end = _utc(comparison.as_of)
    for epoch in comparison.live_epochs:
        observed_at = _utc(epoch.started_at)
        if observed_at < started or observed_at > end:
            continue
        label = _strategy_label(epoch.strategy_key)
        events.append(
            {
                "kind": "STRATEGY_ACTIVATION",
                "time": _epoch(observed_at),
                "value": _live_value_at(comparison, observed_at),
                "label": f"STRAT · {label}",
                "detail": label,
                "position": "belowBar",
                "shape": "circle",
                "color": "#2563eb",
            }
        )
    events.extend(_manual_saxo_events(comparison))
    events.sort(key=lambda item: (int(item["time"]), str(item["kind"]), str(item["label"])))
    return events


__all__ = [
    "MANUAL_SAXO_ANOMALY_KINDS_V1",
    "build_live_pnl_provenance_events_v1",
    "build_live_pnl_strategy_epochs_v1",
]
