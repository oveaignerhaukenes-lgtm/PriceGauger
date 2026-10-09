from __future__ import annotations

"""Read-only, account-scoped V3 LIVE state for human-readable instance controls.

The runtime persists its last heartbeat as free text. We only expose numbers
explicitly present in that heartbeat; no live Saxo calls, inferred positions,
trading decisions or authority writes occur in this projection.
"""

from dataclasses import dataclass
import re
from database import connect

_AMOUNT_RE = re.compile(r"(?<![\w])(?:actual|target)=([-+]?(?:\d+(?:\.\d*)?|\.\d+))(?![\w])")


@dataclass(frozen=True, slots=True)
class V3LiveTruthV1:
    status: str
    detail: str
    updated_at: str | None
    actual: float | None
    target: float | None
    reason: str
    last_execution: str | None


def _quantity(detail: str, name: str) -> float | None:
    for match in _AMOUNT_RE.finditer(detail):
        if match.group(0).startswith(name + "="):
            return float(match.group(1))
    return None


def _reason(status: str, detail: str) -> str:
    info = detail.casefold()
    state = status.upper()
    if "capital cap reached" in info or "capital capacity reached" in info:
        return "PG-kapitalgrense: videre oppbygging stanset"
    if "margin capacity reached" in info:
        return "Saxo-marginkapasitet: videre oppbygging stanset"
    if "already reconciled" in info or "already exists" in info:
        return "Ordreintensjon allerede registrert: ingen duplikatordre"
    if state == "BLOCKED":
        return "BLOKKERT: se siste runtime-melding"
    if state in ("PENDING", "SUBMITTING", "SUBMITTED", "UNKNOWN"):
        return "Ordreavklaring pågår: ingen ny ordre før avstemming"
    if state == "RECONCILED":
        return "Forrige ordre avstemt mot Saxo"
    if state in ("READY", "MANAGING"):
        return "Strategien evalueres / følger målposisjon"
    return "Ingen bekreftet runtime-tilstand"


def load_v3_live_truth_v1(*, instance_id: str, account_id: str, uic: int,
                           asset_type: str, db_path: str = "pricegauger.db") -> V3LiveTruthV1:
    status, detail, updated_at = "NO HEARTBEAT", "", None
    last_execution = None
    with connect(db_path) as db:
        try:
            row = db.execute(
                "SELECT status,detail,updated_at FROM autotrader_v3_live_runtime_state WHERE trader_id=?",
                (str(instance_id),),
            ).fetchone()
            if row is not None:
                value = (lambda key, index: row[key] if isinstance(row, dict) else row[index])
                status = str(value("status", 0) or "UNKNOWN")
                detail = str(value("detail", 1) or "")
                timestamp = value("updated_at", 2)
                updated_at = str(timestamp) if timestamp is not None else None
        except Exception:
            # Missing/rolling-out heartbeat is not proof that a strategy is idle.
            status = "UNKNOWN"
        try:
            row = db.execute(
                """SELECT action,side,amount,executed_at FROM autotrader_v3_execution_events
                   WHERE instance_id=? AND account_id=? AND uic=? AND asset_type=?
                   ORDER BY executed_at DESC, request_key DESC LIMIT 1""",
                (str(instance_id), str(account_id), int(uic), str(asset_type)),
            ).fetchone()
            if row is not None:
                value = (lambda key, index: row[key] if isinstance(row, dict) else row[index])
                last_execution = (
                    f'{value("action", 0)} {value("side", 1)} '
                    f'{float(value("amount", 2)):g} lot · {value("executed_at", 3)}'
                )
        except Exception:
            # During schema rollout, the historical event projection can be absent.
            pass
    return V3LiveTruthV1(
        status=status, detail=detail, updated_at=updated_at,
        actual=_quantity(detail, "actual"), target=_quantity(detail, "target"),
        reason=_reason(status, detail), last_execution=last_execution,
    )


def inventory_label_v1(amount: float | None) -> str:
    if amount is None:
        return "ukjent"
    if abs(amount) < 1e-9:
        return "FLAT 0 lot"
    return ("LONG" if amount > 0 else "SHORT") + f" {abs(amount):g} lot"


__all__ = ["V3LiveTruthV1", "load_v3_live_truth_v1", "inventory_label_v1"]
