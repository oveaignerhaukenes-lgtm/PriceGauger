from __future__ import annotations

"""Read-only global health model for the canonical AutoTrader V3 fleet."""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib

from autotrader_v3_control_plane_v1 import authority_state_v3
from autotrader_v3_instance_registry_v1 import bootstrap_v3_instances_from_enrollments_v1
from autotrader_v3_live_saxo_v1 import configured_live_pilot_client_v3
from database import connect, using_postgres


PENDING_WARNING_SECONDS = 15.0
PENDING_CRITICAL_SECONDS = 60.0
LIVE_HEARTBEAT_CRITICAL_SECONDS = 20.0 * 60.0

_RED_RUNTIME_STATES = {"BLOCKED", "FAILED", "UNKNOWN"}
_YELLOW_RUNTIME_STATES = {"PENDING", "DEGRADED"}


@dataclass(frozen=True, slots=True)
class AutoTraderInstanceHealthV1:
    instance_id: str
    market_name: str
    account_id: str
    account_name: str
    uic: int
    live_armed: bool
    sim_armed: bool
    runtime_status: str
    runtime_detail: str
    runtime_updated_at: datetime | None
    pending_request_key: str | None
    pending_state: str | None
    pending_age_seconds: float | None
    broker_order_id: str | None
    broker_working: bool | None
    market_open: bool | None
    market_state: str | None
    open_pnl: float | None
    trades_24h: int
    severity: str
    issue_code: str | None
    issue_message: str | None


@dataclass(frozen=True, slots=True)
class AutoTraderHealthSnapshotV1:
    state: str
    label: str
    instances: tuple[AutoTraderInstanceHealthV1, ...]
    live_count: int
    sim_count: int
    unresolved_orders: int
    trades_24h: int
    open_pnl: float | None
    critical_messages: tuple[str, ...]
    alert_fingerprint: str | None


def _utc(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _age_seconds(value, *, now: datetime) -> float | None:
    parsed = _utc(value)
    if parsed is None:
        return None
    return max(0.0, (now - parsed).total_seconds())


def _runtime(instance_id: str):
    try:
        with connect() as db:
            row = db.execute(
                "SELECT status,detail,updated_at FROM autotrader_v3_live_runtime_state WHERE trader_id=?",
                (instance_id,),
            ).fetchone()
    except Exception:
        return "NO HEARTBEAT", "", None
    if row is None:
        return "NO HEARTBEAT", "", None
    get = lambda key, index: row[key] if isinstance(row, dict) else row[index]
    return str(get("status", 0) or "UNKNOWN"), str(get("detail", 1) or ""), _utc(get("updated_at", 2))


def _pending(instance):
    try:
        with connect() as db:
            row = db.execute(
                """SELECT request_key,state,broker_order_id,updated_at
                   FROM autotrader_v3_order_guard
                   WHERE account_id=? AND uic=? AND asset_type=?
                     AND state IN ('RESERVED','SUBMITTING','SUBMITTED','UNKNOWN')
                   ORDER BY updated_at DESC LIMIT 1""",
                (instance.account_id, int(instance.uic), instance.asset_type),
            ).fetchone()
    except Exception:
        return None
    if row is None:
        return None
    get = lambda key, index: row[key] if isinstance(row, dict) else row[index]
    return {
        "request_key": str(get("request_key", 0)),
        "state": str(get("state", 1)),
        "broker_order_id": str(get("broker_order_id", 2) or "") or None,
        "updated_at": get("updated_at", 3),
    }


def _working_order_ids_v1(broker) -> set[str] | None:
    """Return active Saxo OrderIds, or None when broker state cannot be read."""
    if broker is None:
        return None
    try:
        payload = broker.client._get("port/v1/orders/me", params={"$top": 1000})
        rows = payload.get("Data")
        if not isinstance(rows, list):
            return None
        return {
            str(row.get("OrderId") or "").strip()
            for row in rows
            if isinstance(row, dict) and str(row.get("OrderId") or "").strip()
        }
    except Exception:
        return None


def _trades_24h(instance_id: str) -> int:
    try:
        sql = (
            "SELECT count(*) AS n FROM autotrader_v3_execution_events "
            "WHERE instance_id=? AND executed_at>=now()-INTERVAL '24 hours'"
            if using_postgres()
            else "SELECT count(*) AS n FROM autotrader_v3_execution_events "
                 "WHERE instance_id=? AND executed_at>=datetime('now','-24 hours')"
        )
        with connect() as db:
            row = db.execute(sql, (instance_id,)).fetchone()
        if row is None:
            return 0
        return int(row["n"] if isinstance(row, dict) else row[0])
    except Exception:
        return 0


def classify_instance_health_v1(
    *,
    live_armed: bool,
    runtime_status: str,
    runtime_detail: str,
    runtime_age_seconds: float | None,
    pending_state: str | None,
    pending_age_seconds: float | None,
    broker_working: bool | None = None,
    market_open: bool | None = None,
    market_state: str | None = None,
) -> tuple[str, str | None, str | None]:
    """Return severity, stable issue code and operator-facing explanation."""

    status = str(runtime_status or "UNKNOWN").upper()
    pending = str(pending_state or "").upper()

    if pending == "UNKNOWN":
        return (
            "RED",
            "ORDER_UNKNOWN",
            "Saxo-ordrens resultat er ukjent. Ingen ny ordre sendes før posisjonen er avklart.",
        )
    if pending == "SUBMITTED" and broker_working is True:
        if market_open is False:
            state_text = f" ({market_state})" if market_state else ""
            return (
                "YELLOW",
                "ORDER_WORKING_MARKET_CLOSED",
                f"Ordren er fortsatt aktiv hos Saxo. Markedet er stengt{state_text}; AutoTrader venter på utførelse.",
            )
        return (
            "YELLOW",
            "ORDER_WORKING",
            "Ordren er fortsatt aktiv hos Saxo og venter på utførelse.",
        )
    if pending and pending_age_seconds is not None and pending_age_seconds >= PENDING_CRITICAL_SECONDS:
        return (
            "RED",
            "ORDER_STUCK",
            f"Ordren har stått {pending} i {pending_age_seconds:.0f} s uten bekreftet inventory-endring.",
        )
    if status in _RED_RUNTIME_STATES:
        return (
            "RED",
            f"RUNTIME_{status}",
            runtime_detail or f"AutoTrader runtime er {status}.",
        )
    if live_armed and runtime_age_seconds is not None and runtime_age_seconds >= LIVE_HEARTBEAT_CRITICAL_SECONDS:
        return (
            "RED",
            "HEARTBEAT_STALE",
            f"LIVE worker-heartbeat er {runtime_age_seconds / 60.0:.1f} min gammel.",
        )
    if live_armed and status == "NO HEARTBEAT":
        return (
            "YELLOW",
            "NO_HEARTBEAT",
            "LIVE er armert, men det finnes ennå ingen worker-heartbeat.",
        )
    if pending and pending_age_seconds is not None and pending_age_seconds >= PENDING_WARNING_SECONDS:
        return (
            "YELLOW",
            "ORDER_PENDING",
            f"Venter på Saxo-reconciliation ({pending_age_seconds:.0f} s).",
        )
    if live_armed and market_open is False:
        state_text = f" ({market_state})" if market_state else ""
        return (
            "YELLOW",
            "MARKET_CLOSED",
            f"Markedet er stengt{state_text}. AutoTrader er armert og venter på at Saxo åpner markedet.",
        )
    if status in _YELLOW_RUNTIME_STATES:
        return (
            "YELLOW",
            f"RUNTIME_{status}",
            runtime_detail or f"AutoTrader runtime er {status}.",
        )
    return "GREEN" if live_armed else "IDLE", None, None


def load_autotrader_health_snapshot_v1(*, include_pnl: bool = True, now: datetime | None = None) -> AutoTraderHealthSnapshotV1:
    """Load a fail-open read model. It never changes authority or submits orders."""

    current = now or datetime.now(timezone.utc)
    instances = bootstrap_v3_instances_from_enrollments_v1()
    broker = configured_live_pilot_client_v3() if include_pnl else None
    account_names: dict[str, str] = {}
    working_order_ids: set[str] | None = None
    if broker is not None:
        try:
            for row in broker.accounts():
                if not isinstance(row, dict):
                    continue
                account_id = str(row.get("AccountId") or "").strip()
                if account_id:
                    account_names[account_id] = str(
                        row.get("AccountName") or row.get("DisplayName") or ""
                    ).strip()
        except Exception:
            broker = None
        if broker is not None:
            working_order_ids = _working_order_ids_v1(broker)

    rows: list[AutoTraderInstanceHealthV1] = []
    for instance in instances:
        try:
            authority = authority_state_v3(instance.instance_id)
            live_armed = bool(authority.live_armed)
            sim_armed = bool(authority.sim_armed)
        except Exception:
            live_armed = False
            sim_armed = False

        runtime_status, runtime_detail, runtime_at = _runtime(instance.instance_id)
        runtime_age = _age_seconds(runtime_at, now=current)
        pending = _pending(instance)
        pending_age = _age_seconds(pending["updated_at"], now=current) if pending else None
        broker_working = None
        market_open = None
        market_state = None
        if pending and pending.get("broker_order_id") and working_order_ids is not None:
            broker_working = str(pending["broker_order_id"]) in working_order_ids
        if broker is not None and (live_armed or sim_armed):
            try:
                market = broker.market_status_exact(
                    account_id=instance.account_id,
                    uic=int(instance.uic),
                    asset_type=instance.asset_type,
                )
                market_open = market.is_open
                market_state = market.market_state
            except Exception:
                market_open = None
                market_state = None

        severity, issue_code, issue_message = classify_instance_health_v1(
            live_armed=live_armed,
            runtime_status=runtime_status,
            runtime_detail=runtime_detail,
            runtime_age_seconds=runtime_age,
            pending_state=pending["state"] if pending else None,
            pending_age_seconds=pending_age,
            broker_working=broker_working,
            market_open=market_open,
            market_state=market_state,
        )

        pnl = None
        if include_pnl and broker is not None:
            try:
                pnl = float(
                    broker.open_pnl_exact(
                        account_id=instance.account_id,
                        uic=int(instance.uic),
                        asset_type=instance.asset_type,
                    )
                )
            except Exception:
                pnl = None

        rows.append(
            AutoTraderInstanceHealthV1(
                instance_id=instance.instance_id,
                market_name=instance.market_name,
                account_id=instance.account_id,
                account_name=account_names.get(instance.account_id, ""),
                uic=int(instance.uic),
                live_armed=live_armed,
                sim_armed=sim_armed,
                runtime_status=runtime_status,
                runtime_detail=runtime_detail,
                runtime_updated_at=runtime_at,
                pending_request_key=pending["request_key"] if pending else None,
                pending_state=pending["state"] if pending else None,
                pending_age_seconds=pending_age,
                broker_order_id=pending["broker_order_id"] if pending else None,
                broker_working=broker_working,
                market_open=market_open,
                market_state=market_state,
                open_pnl=pnl,
                trades_24h=_trades_24h(instance.instance_id),
                severity=severity,
                issue_code=issue_code,
                issue_message=issue_message,
            )
        )

    critical = tuple(
        f"{row.market_name}: {row.issue_message}"
        for row in rows
        if row.severity == "RED" and row.issue_message
    )
    if critical:
        state, label = "RED", "Feil"
    elif any(row.severity == "YELLOW" for row in rows):
        state, label = "YELLOW", "Venter"
    elif any(row.live_armed for row in rows):
        state, label = "GREEN", "Kjører"
    else:
        state, label = "IDLE", "Av"

    fingerprint = None
    if critical:
        material = "|".join(
            sorted(
                f"{row.instance_id}:{row.issue_code}:{row.pending_request_key or ''}:{row.runtime_detail}"
                for row in rows
                if row.severity == "RED"
            )
        )
        fingerprint = hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]

    pnl_values = [row.open_pnl for row in rows if row.open_pnl is not None]
    return AutoTraderHealthSnapshotV1(
        state=state,
        label=label,
        instances=tuple(rows),
        live_count=sum(1 for row in rows if row.live_armed),
        sim_count=sum(1 for row in rows if row.sim_armed),
        unresolved_orders=sum(1 for row in rows if row.pending_state),
        trades_24h=sum(row.trades_24h for row in rows),
        open_pnl=sum(float(value) for value in pnl_values) if pnl_values else None,
        critical_messages=critical,
        alert_fingerprint=fingerprint,
    )


__all__ = [
    "AutoTraderHealthSnapshotV1",
    "AutoTraderInstanceHealthV1",
    "PENDING_CRITICAL_SECONDS",
    "classify_instance_health_v1",
    "load_autotrader_health_snapshot_v1",
]
