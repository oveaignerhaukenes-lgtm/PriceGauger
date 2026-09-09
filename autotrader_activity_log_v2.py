from __future__ import annotations

"""Simple-Core facade for the durable AutoManager activity log."""

from dataclasses import replace
from typing import Any

import autotrader_activity_log_legacy_v2 as _legacy
from autotrader_activity_log_legacy_v2 import *  # noqa: F401,F403
from database import connect as _default_connect


# Kept as a module binding so existing focused tests and diagnostics can inject a DB.
connect = _default_connect
ENGINE_AUTOMANAGER = "AutoManager"
_legacy.ENGINE_AUTOMANAGER = ENGINE_AUTOMANAGER
_original_build = _legacy.build_automanager_lifecycle_status_v2


_INTERNAL_BLOCK_REASONS = {
    "LIVE_ENROLLMENT_MISMATCH",
    "POSITION_NOT_EXACTLY_MANAGED",
    "STALE_POSITION_BASIS",
    "ALREADY_FLAT_NO_ORDER",
    "NEWER_FAST_SIGNAL",
}


def _record(row: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    if isinstance(row, dict):
        return dict(row)
    return dict(zip(keys, row))


def _event_key(value: Any) -> str:
    return _legacy._utc(value).isoformat()


def _execution_stage(status: str | None, block_reason: str | None) -> str:
    normalized = str(status or "").strip().upper()
    reason = str(block_reason or "").strip().upper()
    if normalized == "BLOCKED":
        if reason in _INTERNAL_BLOCK_REASONS or reason.startswith("PG_"):
            return "PG safety"
        return "gate/precheck"
    if normalized in {"SUBMITTING", "ORDER_ACCEPTED", "REJECTED", "UNCERTAIN"}:
        return "Saxo submit"
    if normalized == "RECONCILED":
        return "broker reconcile"
    if normalized in {"PENDING", "APPROVED"}:
        return "PG queue"
    if normalized == "SUPERSEDED":
        return "strategy supersede"
    return "strategy"


def _target_title(item: dict[str, Any]) -> str | None:
    desired = str(item.get("desired_direction") or "").upper()
    observed = str(item.get("observed_direction") or "FLAT").upper()
    action = str(item.get("requested_action") or "").upper()
    if desired not in {"LONG", "SHORT", "FLAT"}:
        return None
    target_label = f"MACD {desired}" if desired in {"LONG", "SHORT"} else "Strategi FLAT"
    if action == "CLOSE":
        return f"{target_label} → CLOSE {observed}"
    if action == "OPEN":
        return f"{target_label} → OPEN {desired}"
    return f"{target_label} → HOLD"


def _debug_detail(item: dict[str, Any]) -> str:
    observed = str(item.get("observed_direction") or "FLAT").upper()
    desired = str(item.get("desired_direction") or "—").upper()
    action = str(item.get("requested_action") or "NONE").upper()
    status = str(item.get("status") or "NO_REQUEST").upper()
    reason = str(item.get("block_reason") or "").strip()
    request_id = str(item.get("request_id") or "").strip()
    order_id = str(item.get("order_id") or "").strip()

    parts = [
        f"observed={observed}",
        f"target={desired}",
        f"action={action}",
        f"status={status}",
        f"stage={_execution_stage(status, reason)}",
    ]
    if request_id:
        parts.append(f"request={request_id[:8]}")
    if order_id:
        parts.append(f"order={order_id}")
    if reason:
        parts.append(f"reason={reason}")
    return "Debug: " + " · ".join(parts)


def _load_strategy_debug_rows(pilot_key: str, *, limit: int) -> dict[str, dict[str, Any]]:
    keys = (
        "signal_at",
        "signal",
        "requested_action",
        "desired_direction",
        "observed_direction",
        "request_id",
        "status",
        "block_reason",
        "order_id",
    )
    with connect() as db:
        rows = db.execute(
            """
            SELECT e.signal_at, e.signal, e.requested_action, e.desired_direction,
                   e.observed_direction, r.request_id, r.status, r.block_reason, r.order_id
            FROM pg_v2_autotrader_strategy_evaluations e
            LEFT JOIN pg_v2_autotrader_execution_requests r
              ON r.request_id = e.execution_request_id
            WHERE e.pilot_key = ? AND e.signal IS NOT NULL
            ORDER BY e.signal_at DESC, e.created_at DESC
            LIMIT ?
            """,
            (pilot_key, max(1, int(limit))),
        ).fetchall()
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = _record(row, keys)
        key = _event_key(item["signal_at"])
        # Multiple durable evaluations can refer to the same signal. The query is
        # newest-first; keep the latest lifecycle snapshot for the card.
        result.setdefault(key, item)
    return result


def build_automanager_lifecycle_status_v2(
    enrollment,
    *,
    observed_direction: str,
    latest_strategy_close_signal=None,
    latest_strategy_close_at=None,
    latest_guardian_reason=None,
    latest_guardian_close_at=None,
    pending_action=None,
    pending_status=None,
    pending_block_reason=None,
    exact_close_authority=None,
):
    """Describe runtime state without exposing legacy user-confirmation gates."""
    direction = str(observed_direction or "FLAT").upper()
    if direction != "FLAT" and exact_close_authority is False:
        return (
            f"{direction} · registrerer AutoManager-basis",
            "AutoManager registrerer eksakt Saxo-basis automatisk før neste CLOSE; ingen brukerbekreftelse kreves.",
        )

    status, next_step = _original_build(
        enrollment,
        observed_direction=observed_direction,
        latest_strategy_close_signal=latest_strategy_close_signal,
        latest_strategy_close_at=latest_strategy_close_at,
        latest_guardian_reason=latest_guardian_reason,
        latest_guardian_close_at=latest_guardian_close_at,
        pending_action=pending_action,
        pending_status=pending_status,
        pending_block_reason=pending_block_reason,
        exact_close_authority=exact_close_authority,
    )
    status = status.replace("30m MACD-kryss", "strategisignal")
    next_step = next_step.replace(
        "Overvåker neste lukkede 30m-bar; ",
        "Overvåker valgt strategi; ",
    )
    next_step = next_step.replace(" MACD-kryss", " signal")
    next_step = next_step.replace("automatisk re-entry er armed", "automatisk OPEN/re-entry er aktiv")
    return status, next_step


def load_automanager_activity_log_v2(*args, **kwargs):
    # Preserve the legacy loader/read model while making this facade's injectable DB
    # binding authoritative for tests and diagnostics.
    _legacy.connect = connect
    _legacy.build_automanager_lifecycle_status_v2 = build_automanager_lifecycle_status_v2
    _legacy.ENGINE_AUTOMANAGER = ENGINE_AUTOMANAGER
    log = _legacy.load_automanager_activity_log_v2(*args, **kwargs)

    try:
        requested_limit = int(kwargs.get("limit", 12))
        debug_rows = _load_strategy_debug_rows(log.pilot_key, limit=requested_limit)
    except Exception:
        # The activity log is operational UI. Debug enrichment must never make the
        # primary durable event feed unavailable.
        return log

    enriched = []
    for event in log.events:
        if event.engine != ENGINE_AUTOMANAGER:
            enriched.append(event)
            continue
        item = debug_rows.get(_event_key(event.occurred_at))
        if item is None:
            enriched.append(event)
            continue
        title = _target_title(item) or event.title
        detail = f"{event.detail} {_debug_detail(item)}"
        enriched.append(replace(event, title=title, detail=detail))
    return replace(log, events=tuple(enriched))


_legacy.build_automanager_lifecycle_status_v2 = build_automanager_lifecycle_status_v2

__all__ = list(_legacy.__all__)
