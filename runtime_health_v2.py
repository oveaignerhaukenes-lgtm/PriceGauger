from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from database import connect


@dataclass(frozen=True, slots=True)
class RuntimeHealthV2:
    service: str
    stage: str
    status: str
    detail: str
    age_seconds: float | None


def _utc(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def freshness_health_v2(
    *,
    service: str,
    stage: str,
    observed_at: str | datetime | None,
    now: str | datetime | None = None,
    stale_after_seconds: int = 180,
    dead_after_seconds: int = 900,
) -> RuntimeHealthV2:
    if stale_after_seconds <= 0 or dead_after_seconds <= stale_after_seconds:
        raise ValueError("health thresholds must satisfy 0 < stale < dead")
    if observed_at is None:
        return RuntimeHealthV2(service, stage, "NO_DATA", "no observation available", None)

    current = _utc(now or datetime.now(timezone.utc))
    observed = _utc(observed_at)
    age = max(0.0, (current - observed).total_seconds())
    if age <= stale_after_seconds:
        status = "HEALTHY"
    elif age <= dead_after_seconds:
        status = "STALE"
    else:
        status = "DEGRADED"
    return RuntimeHealthV2(
        service=service,
        stage=stage,
        status=status,
        detail=f"latest observation age={age:.1f}s",
        age_seconds=age,
    )


def record_runtime_health_v2(health: RuntimeHealthV2) -> None:
    with connect() as db:
        db.execute(
            """
            INSERT INTO pg_v2_runtime_status(service, stage, status, detail, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT (service, stage) DO UPDATE SET
                status = EXCLUDED.status,
                detail = EXCLUDED.detail,
                updated_at = CURRENT_TIMESTAMP
            """,
            (health.service, health.stage, health.status, health.detail),
        )


def load_runtime_health_v2(*, service: str | None = None) -> tuple[RuntimeHealthV2, ...]:
    with connect() as db:
        if service is None:
            rows = db.execute(
                """
                SELECT service, stage, status, detail
                FROM pg_v2_runtime_status
                ORDER BY service, stage
                """
            ).fetchall()
        else:
            rows = db.execute(
                """
                SELECT service, stage, status, detail
                FROM pg_v2_runtime_status
                WHERE service = ?
                ORDER BY stage
                """,
                (service,),
            ).fetchall()

    result: list[RuntimeHealthV2] = []
    for row in rows:
        get = (lambda key, index: row[key]) if isinstance(row, dict) else (lambda key, index: row[index])
        result.append(
            RuntimeHealthV2(
                service=str(get("service", 0)),
                stage=str(get("stage", 1)),
                status=str(get("status", 2)),
                detail=str(get("detail", 3) or ""),
                age_seconds=None,
            )
        )
    return tuple(result)
