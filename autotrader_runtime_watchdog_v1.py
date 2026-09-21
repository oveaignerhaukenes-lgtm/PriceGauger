from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import json
import logging
import time
from typing import Any, Mapping, Sequence
from uuid import NAMESPACE_URL, uuid5

from autotrader_fast_live_runtime_v2 import (
    DIRECTION_FLAT,
    DIRECTION_LONG,
    DIRECTION_SHORT,
    _exact_product_observation,
    _observed_direction,
)
from autotrader_manage_control_v1 import auto_manage_enabled_v1
from autotrader_mtf_entry_shadow_v2 import closed_bars_v2, macd_observations_v2
from autotrader_risk_control_v2 import PositionObservationV2, _position_observations_v2
from autotrader_strategy_catalog_v2 import MACD_NORM_MANAGER_STRATEGY_V1, MACD_NORM_STRATEGY_V1
from autotrader_strategy_enrollment_v2 import (
    EXECUTION_MODE_LIVE,
    StrategyEnrollmentV2,
    load_active_strategy_enrollments_v2,
)
from autotrader_macd_timeframe_live_v1 import LIVE_MACD_CONTROL_STRATEGIES_V1
from autotrader_strategy_family_v1 import (
    FAMILY_MACD_STRATEGY_V1,
    FAMILY_MACD_V1,
    load_strategy_family_config_v1,
)
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from database import connect, using_postgres
from saxo_provider import configured_client


LOGGER = logging.getLogger("pricegauger.autotrader.runtime_watchdog_v1")

WATCHDOG_INTERVAL_SECONDS_V1 = 15
WATCHDOG_REPORT_SECONDS_V1 = 60
TARGET_OPPOSITE_GRACE_SECONDS_V1 = 45
TARGET_NOT_REACHED_GRACE_SECONDS_V1 = 90
PENDING_STUCK_SECONDS_V1 = 120
REQUEST_STUCK_SECONDS_V1 = {
    "PENDING": 90,
    "APPROVED": 90,
    "SUBMITTING": 30,
    "ORDER_ACCEPTED": 90,
    "UNCERTAIN": 30,
}
DIRECTIONS_V1 = {DIRECTION_FLAT, DIRECTION_LONG, DIRECTION_SHORT}


@dataclass(frozen=True, slots=True)
class AuthoritativeCrossV1:
    direction: str
    occurred_at: datetime
    timeframe_minutes: int
    previous_spread: float
    current_spread: float


@dataclass(frozen=True, slots=True)
class WatchdogInputV1:
    pilot_key: str
    strategy_key: str
    market_name: str
    desired_direction: str
    observed_direction: str
    pending_target_direction: str | None
    intent_signal_at: datetime | None
    intent_signal: str | None
    latest_request_id: str | None
    latest_request_action: str | None
    latest_request_status: str | None
    latest_request_updated_at: datetime | None
    authoritative_cross: AuthoritativeCrossV1 | None
    authoritative_cross_acknowledged: bool
    auto_manage_enabled: bool


@dataclass(frozen=True, slots=True)
class WatchdogFindingV1:
    finding_key: str
    pilot_key: str
    code: str
    severity: str
    summary: str
    evidence: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class WatchdogReportV1:
    report_id: str
    checked_at: datetime
    pilot_key: str
    strategy_key: str
    market_name: str
    desired_direction: str
    observed_direction: str
    pending_target_direction: str | None
    intent_signal_at: datetime | None
    intent_signal: str | None
    authoritative_cross_direction: str | None
    authoritative_cross_at: datetime | None
    authoritative_cross_timeframe_minutes: int | None
    authoritative_cross_acknowledged: bool
    latest_request_id: str | None
    latest_request_action: str | None
    latest_request_status: str | None
    findings: tuple[WatchdogFindingV1, ...]


def _utc(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _age_seconds(value: datetime | None, *, now: datetime) -> float | None:
    if value is None:
        return None
    return max(0.0, (now - _utc(value)).total_seconds())


def _opposite(left: str, right: str) -> bool:
    return {str(left), str(right)} == {DIRECTION_LONG, DIRECTION_SHORT}


def _finding_key(pilot_key: str, code: str, episode: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"pg-watchdog-v1|{pilot_key}|{code}|{episode}"))


def evaluate_watchdog_contracts_v1(
    snapshot: WatchdogInputV1,
    *,
    now: datetime | None = None,
) -> tuple[WatchdogFindingV1, ...]:
    """Evaluate only invariants; never mutate strategy or execution state."""

    current = _utc(now or datetime.now(timezone.utc))
    if not snapshot.auto_manage_enabled:
        return ()

    findings: list[WatchdogFindingV1] = []
    signal_age = _age_seconds(snapshot.intent_signal_at, now=current)

    cross = snapshot.authoritative_cross
    if cross is not None:
        cross_age = _age_seconds(cross.occurred_at, now=current) or 0.0
        cross_episode = f"{cross.timeframe_minutes}m:{cross.occurred_at.isoformat()}:{cross.direction}"
        if (
            cross_age >= TARGET_OPPOSITE_GRACE_SECONDS_V1
            and not snapshot.authoritative_cross_acknowledged
        ):
            findings.append(
                WatchdogFindingV1(
                    finding_key=_finding_key(
                        snapshot.pilot_key,
                        "AUTHORITATIVE_CROSS_TARGET_MISMATCH",
                        cross_episode,
                    ),
                    pilot_key=snapshot.pilot_key,
                    code="AUTHORITATIVE_CROSS_TARGET_MISMATCH",
                    severity="CRITICAL",
                    summary=(
                        f"{cross.timeframe_minutes}m MACD crossed {cross.direction}, "
                        "but no strategy evaluation acknowledged that authoritative cross."
                    ),
                    evidence={
                        "cross_direction": cross.direction,
                        "cross_at": cross.occurred_at.isoformat(),
                        "timeframe_minutes": cross.timeframe_minutes,
                        "previous_spread": cross.previous_spread,
                        "current_spread": cross.current_spread,
                        "desired_direction": snapshot.desired_direction,
                        "acknowledged": snapshot.authoritative_cross_acknowledged,
                    },
                )
            )
        if (
            cross_age >= TARGET_NOT_REACHED_GRACE_SECONDS_V1
            and snapshot.desired_direction == cross.direction
            and _opposite(snapshot.observed_direction, cross.direction)
        ):
            findings.append(
                WatchdogFindingV1(
                    finding_key=_finding_key(
                        snapshot.pilot_key,
                        "AUTHORITATIVE_CROSS_POSITION_OPPOSITE",
                        cross_episode,
                    ),
                    pilot_key=snapshot.pilot_key,
                    code="AUTHORITATIVE_CROSS_POSITION_OPPOSITE",
                    severity="CRITICAL",
                    summary=(
                        f"{cross.timeframe_minutes}m MACD crossed {cross.direction}, "
                        f"but Saxo exposure is still {snapshot.observed_direction}."
                    ),
                    evidence={
                        "cross_direction": cross.direction,
                        "cross_at": cross.occurred_at.isoformat(),
                        "cross_age_seconds": round(cross_age, 1),
                        "observed_direction": snapshot.observed_direction,
                        "desired_direction": snapshot.desired_direction,
                    },
                )
            )

    episode_at = snapshot.intent_signal_at.isoformat() if snapshot.intent_signal_at else "no-signal-time"
    target_episode = f"{episode_at}:{snapshot.desired_direction}"
    if signal_age is not None and _opposite(snapshot.observed_direction, snapshot.desired_direction):
        if signal_age >= TARGET_OPPOSITE_GRACE_SECONDS_V1:
            findings.append(
                WatchdogFindingV1(
                    finding_key=_finding_key(
                        snapshot.pilot_key,
                        "OPPOSITE_EXPOSURE_AFTER_TARGET",
                        target_episode,
                    ),
                    pilot_key=snapshot.pilot_key,
                    code="OPPOSITE_EXPOSURE_AFTER_TARGET",
                    severity="CRITICAL",
                    summary=(
                        f"Target is {snapshot.desired_direction}, but Saxo remains "
                        f"{snapshot.observed_direction} {signal_age:.0f}s after the signal."
                    ),
                    evidence={
                        "signal": snapshot.intent_signal,
                        "signal_at": episode_at,
                        "signal_age_seconds": round(signal_age, 1),
                        "desired_direction": snapshot.desired_direction,
                        "observed_direction": snapshot.observed_direction,
                    },
                )
            )
    elif (
        signal_age is not None
        and snapshot.desired_direction != snapshot.observed_direction
        and signal_age >= TARGET_NOT_REACHED_GRACE_SECONDS_V1
    ):
        findings.append(
            WatchdogFindingV1(
                finding_key=_finding_key(snapshot.pilot_key, "TARGET_NOT_REACHED", target_episode),
                pilot_key=snapshot.pilot_key,
                code="TARGET_NOT_REACHED",
                severity="WARNING",
                summary=(
                    f"Target {snapshot.desired_direction} has not reached Saxo exposure "
                    f"{snapshot.observed_direction} after {signal_age:.0f}s."
                ),
                evidence={
                    "signal": snapshot.intent_signal,
                    "signal_at": episode_at,
                    "signal_age_seconds": round(signal_age, 1),
                    "desired_direction": snapshot.desired_direction,
                    "observed_direction": snapshot.observed_direction,
                },
            )
        )

    if (
        snapshot.pending_target_direction is not None
        and snapshot.pending_target_direction != snapshot.observed_direction
        and signal_age is not None
        and signal_age >= PENDING_STUCK_SECONDS_V1
    ):
        findings.append(
            WatchdogFindingV1(
                finding_key=_finding_key(
                    snapshot.pilot_key,
                    "PENDING_TRANSITION_STUCK",
                    f"{episode_at}:{snapshot.pending_target_direction}",
                ),
                pilot_key=snapshot.pilot_key,
                code="PENDING_TRANSITION_STUCK",
                severity="WARNING",
                summary=(
                    f"Pending transition to {snapshot.pending_target_direction} has remained "
                    f"unresolved for {signal_age:.0f}s."
                ),
                evidence={
                    "pending_target_direction": snapshot.pending_target_direction,
                    "observed_direction": snapshot.observed_direction,
                    "signal_at": episode_at,
                    "signal_age_seconds": round(signal_age, 1),
                },
            )
        )

    status = str(snapshot.latest_request_status or "").upper()
    threshold = REQUEST_STUCK_SECONDS_V1.get(status)
    request_age = _age_seconds(snapshot.latest_request_updated_at, now=current)
    if threshold is not None and request_age is not None and request_age >= threshold:
        severity = "CRITICAL" if status in {"SUBMITTING", "UNCERTAIN"} else "WARNING"
        findings.append(
            WatchdogFindingV1(
                finding_key=_finding_key(
                    snapshot.pilot_key,
                    "EXECUTION_REQUEST_STUCK",
                    str(snapshot.latest_request_id or status),
                ),
                pilot_key=snapshot.pilot_key,
                code="EXECUTION_REQUEST_STUCK",
                severity=severity,
                summary=(
                    f"{snapshot.latest_request_action or 'execution'} request is still "
                    f"{status} after {request_age:.0f}s."
                ),
                evidence={
                    "request_id": snapshot.latest_request_id,
                    "action": snapshot.latest_request_action,
                    "status": status,
                    "request_age_seconds": round(request_age, 1),
                    "desired_direction": snapshot.desired_direction,
                    "observed_direction": snapshot.observed_direction,
                },
            )
        )

    return tuple(findings)


def ensure_runtime_watchdog_schema_v1() -> None:
    if not using_postgres():
        raise RuntimeError("runtime watchdog requires PostgreSQL")
    with connect() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS pg_v2_autotrader_watchdog_findings (
                finding_key TEXT PRIMARY KEY,
                pilot_key TEXT NOT NULL,
                code TEXT NOT NULL,
                severity TEXT NOT NULL,
                summary TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                opened_at TIMESTAMPTZ NOT NULL,
                last_seen_at TIMESTAMPTZ NOT NULL,
                resolved_at TIMESTAMPTZ,
                occurrence_count INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        db.execute(
            """
            CREATE INDEX IF NOT EXISTS pg_v2_autotrader_watchdog_findings_open_idx
            ON pg_v2_autotrader_watchdog_findings(resolved_at, last_seen_at DESC)
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS pg_v2_autotrader_watchdog_reports (
                report_id UUID PRIMARY KEY,
                pilot_key TEXT NOT NULL,
                strategy_key TEXT NOT NULL,
                market_name TEXT NOT NULL,
                checked_at TIMESTAMPTZ NOT NULL,
                severity TEXT NOT NULL,
                report_json TEXT NOT NULL
            )
            """
        )
        db.execute(
            """
            CREATE INDEX IF NOT EXISTS pg_v2_autotrader_watchdog_reports_time_idx
            ON pg_v2_autotrader_watchdog_reports(checked_at DESC)
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS pg_v2_autotrader_watchdog_status (
                status_id SMALLINT PRIMARY KEY CHECK (status_id = 1),
                checked_at TIMESTAMPTZ NOT NULL,
                evaluated INTEGER NOT NULL,
                failed INTEGER NOT NULL,
                open_findings INTEGER NOT NULL,
                detail TEXT NOT NULL
            )
            """
        )


def _row_mapping(row: Any, columns: Sequence[str]) -> dict[str, Any]:
    if isinstance(row, dict):
        return dict(row)
    return {name: row[index] for index, name in enumerate(columns)}


def _load_runtime_state_v1(enrollment: StrategyEnrollmentV2) -> dict[str, Any]:
    # A triggered X + TakeProfit wrapper temporarily owns the effective target.
    # Read it directly so diagnostics do not mislabel an intentional FLAT/cooldown
    # as a base-strategy target mismatch. The tables may not exist before rollout.
    try:
        with connect() as db:
            tp_row = db.execute(
                """
                SELECT state.triggered_at, state.flat_since,
                       config.enabled, config.reentry_cooldown_seconds
                FROM pg_v2_autotrader_take_profit_state AS state
                JOIN pg_v2_autotrader_take_profit_config AS config
                  ON config.pilot_key = state.pilot_key
                WHERE state.pilot_key = ? AND state.triggered_at IS NOT NULL
                LIMIT 1
                """,
                (enrollment.pilot_key,),
            ).fetchone()
    except Exception:
        tp_row = None
    if tp_row is not None:
        tp = _row_mapping(
            tp_row,
            ("triggered_at", "flat_since", "enabled", "reentry_cooldown_seconds"),
        )
        flat_since = tp.get("flat_since")
        cooldown = max(0, int(tp.get("reentry_cooldown_seconds") or 0))
        latch_active = flat_since is None
        if flat_since is not None and bool(tp.get("enabled")):
            latch_active = datetime.now(timezone.utc) < (
                _utc(flat_since) + timedelta(seconds=cooldown)
            )
        if bool(tp.get("enabled")) and latch_active:
            return {
                "desired_direction": DIRECTION_FLAT,
                "pending_target_direction": DIRECTION_FLAT if flat_since is None else None,
                "intent_signal_at": tp.get("triggered_at"),
                "intent_signal": "TAKE_PROFIT_GIVEBACK",
                "last_action_at": tp.get("triggered_at"),
            }

    columns = (
        "desired_direction",
        "pending_target_direction",
        "intent_signal_at",
        "intent_signal",
        "last_action_at",
    )
    with connect() as db:
        row = db.execute(
            """
            SELECT desired_direction, pending_target_direction, intent_signal_at,
                   intent_signal, last_action_at
            FROM pg_v2_autotrader_fast_live_state
            WHERE pilot_key = ?
            """,
            (enrollment.pilot_key,),
        ).fetchone()
        if row is not None:
            return _row_mapping(row, columns)

        fallback = db.execute(
            """
            SELECT desired_direction, target_direction, signal_at, signal,
                   latest_closed_bar_time
            FROM pg_v2_autotrader_strategy_evaluations
            WHERE pilot_key = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (enrollment.pilot_key,),
        ).fetchone()
    if fallback is None:
        return {
            "desired_direction": DIRECTION_FLAT,
            "pending_target_direction": None,
            "intent_signal_at": None,
            "intent_signal": None,
            "last_action_at": None,
        }
    values = _row_mapping(
        fallback,
        (
            "desired_direction",
            "target_direction",
            "signal_at",
            "signal",
            "latest_closed_bar_time",
        ),
    )
    desired = str(values.get("desired_direction") or values.get("target_direction") or DIRECTION_FLAT)
    return {
        "desired_direction": desired,
        "pending_target_direction": None,
        "intent_signal_at": values.get("signal_at"),
        "intent_signal": values.get("signal"),
        "last_action_at": values.get("latest_closed_bar_time"),
    }


def _latest_request_v1(pilot_key: str) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute(
            """
            SELECT request_id, action, desired_direction, status, block_reason,
                   signal_at, created_at, updated_at
            FROM pg_v2_autotrader_execution_requests
            WHERE pilot_key = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (pilot_key,),
        ).fetchone()
    if row is None:
        return None
    return _row_mapping(
        row,
        (
            "request_id",
            "action",
            "desired_direction",
            "status",
            "block_reason",
            "signal_at",
            "created_at",
            "updated_at",
        ),
    )


def _authoritative_timeframe_v1(strategy_key: str) -> int | None:
    key = str(strategy_key)
    if key in {MACD_NORM_STRATEGY_V1, MACD_NORM_MANAGER_STRATEGY_V1}:
        return 5
    value = LIVE_MACD_CONTROL_STRATEGIES_V1.get(key)
    return None if value is None else int(value)


def _latest_authoritative_cross_v1(
    enrollment: StrategyEnrollmentV2,
    *,
    now: datetime,
    store: CanonicalMarketBarStoreV2,
) -> AuthoritativeCrossV1 | None:
    timeframe = _authoritative_timeframe_v1(enrollment.strategy_key)
    if enrollment.strategy_key == FAMILY_MACD_STRATEGY_V1:
        family_config = load_strategy_family_config_v1(
            enrollment.pilot_key,
            strategy_key=enrollment.strategy_key,
        )
        if family_config is None or family_config.family != FAMILY_MACD_V1:
            return None
        timeframe = int(family_config.timeframe_minutes)
    if timeframe is None:
        return None
    lookback = max(timedelta(hours=8), timedelta(minutes=timeframe * 80))
    bars = store.load_instrument_range(
        instrument_id=int(enrollment.instrument_id),
        start=now - lookback,
        end=now,
        limit=20_000,
    )
    if not bars:
        return None
    closed = closed_bars_v2(
        tuple(item.point for item in bars),
        market=enrollment.market_name,
        timeframe_minutes=timeframe,
    )
    observations = macd_observations_v2(closed, timeframe_minutes=timeframe)
    expected = timedelta(minutes=timeframe)
    for previous, current in reversed(tuple(zip(observations, observations[1:]))):
        if current.closed_at - previous.closed_at != expected:
            continue
        if previous.spread <= 0.0 < current.spread:
            return AuthoritativeCrossV1(
                direction=DIRECTION_LONG,
                occurred_at=_utc(current.closed_at),
                timeframe_minutes=timeframe,
                previous_spread=float(previous.spread),
                current_spread=float(current.spread),
            )
        if previous.spread >= 0.0 > current.spread:
            return AuthoritativeCrossV1(
                direction=DIRECTION_SHORT,
                occurred_at=_utc(current.closed_at),
                timeframe_minutes=timeframe,
                previous_spread=float(previous.spread),
                current_spread=float(current.spread),
            )
    return None


def _cross_acknowledged_v1(
    pilot_key: str,
    cross: AuthoritativeCrossV1 | None,
) -> bool:
    if cross is None:
        return False
    with connect() as db:
        before = db.execute(
            """
            SELECT COALESCE(desired_direction, target_direction) AS desired
            FROM pg_v2_autotrader_strategy_evaluations
            WHERE pilot_key = ? AND created_at <= ?
              AND COALESCE(desired_direction, target_direction) IS NOT NULL
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (pilot_key, cross.occurred_at),
        ).fetchone()
        after = db.execute(
            """
            SELECT 1
            FROM pg_v2_autotrader_strategy_evaluations
            WHERE pilot_key = ?
              AND created_at > ?
              AND created_at <= ?
              AND COALESCE(desired_direction, target_direction) = ?
            LIMIT 1
            """,
            (
                pilot_key,
                cross.occurred_at,
                cross.occurred_at + timedelta(seconds=TARGET_OPPOSITE_GRACE_SECONDS_V1),
                cross.direction,
            ),
        ).fetchone()
    if before is not None:
        values = _row_mapping(before, ("desired",))
        if str(values.get("desired") or "").upper() == cross.direction:
            return True
    return after is not None


def _report_severity(findings: Sequence[WatchdogFindingV1]) -> str:
    levels = {item.severity for item in findings}
    if "CRITICAL" in levels:
        return "CRITICAL"
    if "WARNING" in levels:
        return "WARNING"
    return "OK"


def _build_report_v1(snapshot: WatchdogInputV1, findings: tuple[WatchdogFindingV1, ...], *, now: datetime) -> WatchdogReportV1:
    cross = snapshot.authoritative_cross
    report_id = str(
        uuid5(
            NAMESPACE_URL,
            f"pg-watchdog-report-v1|{snapshot.pilot_key}|{now.isoformat()}",
        )
    )
    return WatchdogReportV1(
        report_id=report_id,
        checked_at=now,
        pilot_key=snapshot.pilot_key,
        strategy_key=snapshot.strategy_key,
        market_name=snapshot.market_name,
        desired_direction=snapshot.desired_direction,
        observed_direction=snapshot.observed_direction,
        pending_target_direction=snapshot.pending_target_direction,
        intent_signal_at=snapshot.intent_signal_at,
        intent_signal=snapshot.intent_signal,
        authoritative_cross_direction=None if cross is None else cross.direction,
        authoritative_cross_at=None if cross is None else cross.occurred_at,
        authoritative_cross_timeframe_minutes=None if cross is None else cross.timeframe_minutes,
        authoritative_cross_acknowledged=snapshot.authoritative_cross_acknowledged,
        latest_request_id=snapshot.latest_request_id,
        latest_request_action=snapshot.latest_request_action,
        latest_request_status=snapshot.latest_request_status,
        findings=findings,
    )


def _jsonable_report(report: WatchdogReportV1) -> dict[str, Any]:
    data = asdict(report)
    data["checked_at"] = report.checked_at.isoformat()
    data["intent_signal_at"] = None if report.intent_signal_at is None else report.intent_signal_at.isoformat()
    data["authoritative_cross_at"] = (
        None if report.authoritative_cross_at is None else report.authoritative_cross_at.isoformat()
    )
    data["findings"] = [
        {
            **asdict(item),
            "evidence": dict(item.evidence),
        }
        for item in report.findings
    ]
    return data


def _persist_report_if_due_v1(report: WatchdogReportV1) -> None:
    with connect() as db:
        previous = db.execute(
            """
            SELECT checked_at, severity
            FROM pg_v2_autotrader_watchdog_reports
            WHERE pilot_key = ?
            ORDER BY checked_at DESC
            LIMIT 1
            """,
            (report.pilot_key,),
        ).fetchone()
        severity = _report_severity(report.findings)
        if previous is not None:
            values = _row_mapping(previous, ("checked_at", "severity"))
            age = (report.checked_at - _utc(values["checked_at"])).total_seconds()
            if age < WATCHDOG_REPORT_SECONDS_V1 and str(values["severity"]) == severity:
                return
        db.execute(
            """
            INSERT INTO pg_v2_autotrader_watchdog_reports(
                report_id, pilot_key, strategy_key, market_name,
                checked_at, severity, report_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (report_id) DO NOTHING
            """,
            (
                report.report_id,
                report.pilot_key,
                report.strategy_key,
                report.market_name,
                report.checked_at,
                severity,
                json.dumps(_jsonable_report(report), sort_keys=True),
            ),
        )


def _persist_findings_v1(
    *,
    pilot_key: str,
    findings: tuple[WatchdogFindingV1, ...],
    now: datetime,
) -> None:
    active_keys = {item.finding_key for item in findings}
    with connect() as db:
        rows = db.execute(
            """
            SELECT finding_key, code
            FROM pg_v2_autotrader_watchdog_findings
            WHERE pilot_key = ? AND resolved_at IS NULL
            """,
            (pilot_key,),
        ).fetchall()
        for row in rows:
            values = _row_mapping(row, ("finding_key", "code"))
            key = str(values["finding_key"])
            if key in active_keys:
                continue
            db.execute(
                """
                UPDATE pg_v2_autotrader_watchdog_findings
                SET resolved_at = ?, last_seen_at = ?
                WHERE finding_key = ? AND resolved_at IS NULL
                """,
                (now, now, key),
            )
            LOGGER.info(
                "WATCHDOG resolved pilot=%s code=%s finding=%s",
                pilot_key,
                values["code"],
                key,
            )

        for finding in findings:
            existing = db.execute(
                "SELECT opened_at, resolved_at FROM pg_v2_autotrader_watchdog_findings WHERE finding_key = ?",
                (finding.finding_key,),
            ).fetchone()
            if existing is None:
                db.execute(
                    """
                    INSERT INTO pg_v2_autotrader_watchdog_findings(
                        finding_key, pilot_key, code, severity, summary,
                        evidence_json, opened_at, last_seen_at, resolved_at, occurrence_count
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 1)
                    """,
                    (
                        finding.finding_key,
                        finding.pilot_key,
                        finding.code,
                        finding.severity,
                        finding.summary,
                        json.dumps(dict(finding.evidence), sort_keys=True),
                        now,
                        now,
                    ),
                )
                LOGGER.warning(
                    "WATCHDOG anomaly pilot=%s code=%s severity=%s finding=%s summary=%s evidence=%s",
                    finding.pilot_key,
                    finding.code,
                    finding.severity,
                    finding.finding_key,
                    finding.summary,
                    json.dumps(dict(finding.evidence), sort_keys=True),
                )
            else:
                db.execute(
                    """
                    UPDATE pg_v2_autotrader_watchdog_findings
                    SET severity = ?, summary = ?, evidence_json = ?,
                        last_seen_at = ?, occurrence_count = occurrence_count + 1,
                        resolved_at = NULL
                    WHERE finding_key = ?
                    """,
                    (
                        finding.severity,
                        finding.summary,
                        json.dumps(dict(finding.evidence), sort_keys=True),
                        now,
                        finding.finding_key,
                    ),
                )


def _snapshot_for_enrollment_v1(
    enrollment: StrategyEnrollmentV2,
    *,
    observations: tuple[PositionObservationV2, ...],
    now: datetime,
    store: CanonicalMarketBarStoreV2,
) -> WatchdogInputV1:
    state = _load_runtime_state_v1(enrollment)
    observed = _exact_product_observation(enrollment, observations)
    observed_direction = _observed_direction(observed)
    request = _latest_request_v1(enrollment.pilot_key)
    cross = _latest_authoritative_cross_v1(enrollment, now=now, store=store)
    cross_acknowledged = _cross_acknowledged_v1(enrollment.pilot_key, cross)
    desired = str(state.get("desired_direction") or observed_direction).upper()
    if desired not in DIRECTIONS_V1:
        desired = observed_direction
    pending_raw = state.get("pending_target_direction")
    pending = None if pending_raw is None else str(pending_raw).upper()
    return WatchdogInputV1(
        pilot_key=enrollment.pilot_key,
        strategy_key=enrollment.strategy_key,
        market_name=enrollment.market_name,
        desired_direction=desired,
        observed_direction=observed_direction,
        pending_target_direction=pending,
        intent_signal_at=None if state.get("intent_signal_at") is None else _utc(state["intent_signal_at"]),
        intent_signal=None if state.get("intent_signal") is None else str(state["intent_signal"]),
        latest_request_id=None if request is None else str(request.get("request_id") or "") or None,
        latest_request_action=None if request is None else str(request.get("action") or "") or None,
        latest_request_status=None if request is None else str(request.get("status") or "") or None,
        latest_request_updated_at=(
            None
            if request is None or request.get("updated_at") is None
            else _utc(request["updated_at"])
        ),
        authoritative_cross=cross,
        authoritative_cross_acknowledged=cross_acknowledged,
        auto_manage_enabled=auto_manage_enabled_v1(enrollment),
    )


def run_runtime_watchdog_cycle_v1(
    *,
    db_path: str = "pricegauger.db",
    now: datetime | None = None,
    observations: tuple[PositionObservationV2, ...] | None = None,
) -> tuple[WatchdogReportV1, ...]:
    if not using_postgres():
        return ()
    ensure_runtime_watchdog_schema_v1()
    current = _utc(now or datetime.now(timezone.utc))
    enrollments = tuple(
        item
        for item in load_active_strategy_enrollments_v2()
        if item.enabled and item.execution_mode == EXECUTION_MODE_LIVE
    )
    if observations is None:
        client = configured_client()
        if client is None:
            raise RuntimeError("Saxo client is not configured")
        observations = _position_observations_v2(client)

    store = CanonicalMarketBarStoreV2(db_path)
    reports: list[WatchdogReportV1] = []
    failed = 0
    for enrollment in enrollments:
        try:
            snapshot = _snapshot_for_enrollment_v1(
                enrollment,
                observations=observations,
                now=current,
                store=store,
            )
            findings = evaluate_watchdog_contracts_v1(snapshot, now=current)
            report = _build_report_v1(snapshot, findings, now=current)
            _persist_findings_v1(pilot_key=enrollment.pilot_key, findings=findings, now=current)
            _persist_report_if_due_v1(report)
            reports.append(report)
        except Exception as exc:
            failed += 1
            LOGGER.warning(
                "WATCHDOG pilot evaluation failed pilot=%s strategy=%s: %s",
                enrollment.pilot_key,
                enrollment.strategy_key,
                exc,
                exc_info=True,
            )

    open_count = sum(len(item.findings) for item in reports)
    with connect() as db:
        db.execute(
            """
            INSERT INTO pg_v2_autotrader_watchdog_status(
                status_id, checked_at, evaluated, failed, open_findings, detail
            ) VALUES (1, ?, ?, ?, ?, ?)
            ON CONFLICT (status_id) DO UPDATE SET
                checked_at=EXCLUDED.checked_at,
                evaluated=EXCLUDED.evaluated,
                failed=EXCLUDED.failed,
                open_findings=EXCLUDED.open_findings,
                detail=EXCLUDED.detail
            """,
            (
                current,
                len(reports),
                failed,
                open_count,
                "OK" if failed == 0 else f"{failed} pilot evaluations failed",
            ),
        )
    LOGGER.info(
        "WATCHDOG summary checked_at=%s evaluated=%d failed=%d open_findings=%d reports=%s",
        current.isoformat(),
        len(reports),
        failed,
        open_count,
        ",".join(item.report_id for item in reports) or "none",
    )
    return tuple(reports)


def run_runtime_watchdog_forever_v1(
    *,
    db_path: str = "pricegauger.db",
    interval_seconds: int = WATCHDOG_INTERVAL_SECONDS_V1,
) -> None:
    interval = max(10, int(interval_seconds))
    ensure_runtime_watchdog_schema_v1()
    while True:
        started = time.monotonic()
        try:
            run_runtime_watchdog_cycle_v1(db_path=db_path)
        except Exception as exc:
            LOGGER.warning("WATCHDOG cycle failed: %s", exc, exc_info=True)
            try:
                with connect() as db:
                    db.execute(
                        """
                        INSERT INTO pg_v2_autotrader_watchdog_status(
                            status_id, checked_at, evaluated, failed, open_findings, detail
                        ) VALUES (1, now(), 0, 1, 0, ?)
                        ON CONFLICT (status_id) DO UPDATE SET
                            checked_at=EXCLUDED.checked_at,
                            failed=1,
                            detail=EXCLUDED.detail
                        """,
                        (f"{type(exc).__name__}: {exc}",),
                    )
            except Exception:
                pass
        elapsed = time.monotonic() - started
        time.sleep(max(0.5, interval - elapsed))


def load_watchdog_status_v1() -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute(
            """
            SELECT checked_at, evaluated, failed, open_findings, detail
            FROM pg_v2_autotrader_watchdog_status
            WHERE status_id = 1
            """
        ).fetchone()
    if row is None:
        return None
    return _row_mapping(row, ("checked_at", "evaluated", "failed", "open_findings", "detail"))


def load_watchdog_findings_v1(*, limit: int = 100, include_resolved: bool = True) -> tuple[dict[str, Any], ...]:
    clause = "" if include_resolved else "WHERE resolved_at IS NULL"
    with connect() as db:
        rows = db.execute(
            f"""
            SELECT finding_key, pilot_key, code, severity, summary, evidence_json,
                   opened_at, last_seen_at, resolved_at, occurrence_count
            FROM pg_v2_autotrader_watchdog_findings
            {clause}
            ORDER BY COALESCE(resolved_at, last_seen_at) DESC
            LIMIT ?
            """,
            (max(1, int(limit)),),
        ).fetchall()
    columns = (
        "finding_key",
        "pilot_key",
        "code",
        "severity",
        "summary",
        "evidence_json",
        "opened_at",
        "last_seen_at",
        "resolved_at",
        "occurrence_count",
    )
    return tuple(_row_mapping(row, columns) for row in rows)


def load_watchdog_reports_v1(*, limit: int = 50) -> tuple[WatchdogReportV1, ...]:
    with connect() as db:
        rows = db.execute(
            """
            SELECT report_json
            FROM pg_v2_autotrader_watchdog_reports
            ORDER BY checked_at DESC
            LIMIT ?
            """,
            (max(1, int(limit)),),
        ).fetchall()
    reports: list[WatchdogReportV1] = []
    for row in rows:
        raw = row["report_json"] if isinstance(row, dict) else row[0]
        data = json.loads(str(raw))
        findings = tuple(
            WatchdogFindingV1(
                finding_key=str(item["finding_key"]),
                pilot_key=str(item["pilot_key"]),
                code=str(item["code"]),
                severity=str(item["severity"]),
                summary=str(item["summary"]),
                evidence=dict(item.get("evidence") or {}),
            )
            for item in data.get("findings") or []
        )
        reports.append(
            WatchdogReportV1(
                report_id=str(data["report_id"]),
                checked_at=_utc(data["checked_at"]),
                pilot_key=str(data["pilot_key"]),
                strategy_key=str(data["strategy_key"]),
                market_name=str(data["market_name"]),
                desired_direction=str(data["desired_direction"]),
                observed_direction=str(data["observed_direction"]),
                pending_target_direction=data.get("pending_target_direction"),
                intent_signal_at=None if data.get("intent_signal_at") is None else _utc(data["intent_signal_at"]),
                intent_signal=data.get("intent_signal"),
                authoritative_cross_direction=data.get("authoritative_cross_direction"),
                authoritative_cross_at=(
                    None if data.get("authoritative_cross_at") is None else _utc(data["authoritative_cross_at"])
                ),
                authoritative_cross_timeframe_minutes=data.get("authoritative_cross_timeframe_minutes"),
                authoritative_cross_acknowledged=bool(data.get("authoritative_cross_acknowledged", False)),
                latest_request_id=data.get("latest_request_id"),
                latest_request_action=data.get("latest_request_action"),
                latest_request_status=data.get("latest_request_status"),
                findings=findings,
            )
        )
    return tuple(reports)


def load_watchdog_report_by_id_v1(report_id: str) -> WatchdogReportV1 | None:
    target = str(report_id or "").strip()
    if not target:
        return None
    try:
        with connect() as db:
            row = db.execute(
                """
                SELECT report_json
                FROM pg_v2_autotrader_watchdog_reports
                WHERE report_id = ?
                LIMIT 1
                """,
                (target,),
            ).fetchone()
    except Exception:
        return None
    if row is None:
        return None
    raw = row["report_json"] if isinstance(row, dict) else row[0]
    data = json.loads(str(raw))
    findings = tuple(
        WatchdogFindingV1(
            finding_key=str(item["finding_key"]),
            pilot_key=str(item["pilot_key"]),
            code=str(item["code"]),
            severity=str(item["severity"]),
            summary=str(item["summary"]),
            evidence=dict(item.get("evidence") or {}),
        )
        for item in data.get("findings") or []
    )
    return WatchdogReportV1(
        report_id=str(data["report_id"]),
        checked_at=_utc(data["checked_at"]),
        pilot_key=str(data["pilot_key"]),
        strategy_key=str(data["strategy_key"]),
        market_name=str(data["market_name"]),
        desired_direction=str(data["desired_direction"]),
        observed_direction=str(data["observed_direction"]),
        pending_target_direction=data.get("pending_target_direction"),
        intent_signal_at=None if data.get("intent_signal_at") is None else _utc(data["intent_signal_at"]),
        intent_signal=data.get("intent_signal"),
        authoritative_cross_direction=data.get("authoritative_cross_direction"),
        authoritative_cross_at=(
            None if data.get("authoritative_cross_at") is None else _utc(data["authoritative_cross_at"])
        ),
        authoritative_cross_timeframe_minutes=data.get("authoritative_cross_timeframe_minutes"),
        authoritative_cross_acknowledged=bool(data.get("authoritative_cross_acknowledged", False)),
        latest_request_id=data.get("latest_request_id"),
        latest_request_action=data.get("latest_request_action"),
        latest_request_status=data.get("latest_request_status"),
        findings=findings,
    )


def format_watchdog_report_v1(report: WatchdogReportV1) -> str:
    cross = "none"
    if report.authoritative_cross_direction and report.authoritative_cross_at:
        cross = (
            f"{report.authoritative_cross_timeframe_minutes}m "
            f"{report.authoritative_cross_direction} @ {report.authoritative_cross_at.isoformat()}"
        )
    lines = [
        f"PriceGauger watchdog report {report.report_id}",
        f"checked_at: {report.checked_at.isoformat()}",
        f"market: {report.market_name}",
        f"pilot: {report.pilot_key}",
        f"strategy: {report.strategy_key}",
        f"desired: {report.desired_direction}",
        f"observed_saxo: {report.observed_direction}",
        f"pending: {report.pending_target_direction or 'none'}",
        f"signal: {report.intent_signal or 'none'} @ "
        f"{report.intent_signal_at.isoformat() if report.intent_signal_at else 'none'}",
        f"authoritative_cross: {cross} · acknowledged={report.authoritative_cross_acknowledged}",
        f"execution: {report.latest_request_action or 'none'} / "
        f"{report.latest_request_status or 'none'} / {report.latest_request_id or 'none'}",
        f"findings: {len(report.findings)}",
    ]
    for item in report.findings:
        lines.append(f"- [{item.severity}] {item.code}: {item.summary}")
        lines.append(f"  evidence: {json.dumps(dict(item.evidence), sort_keys=True)}")
    if not report.findings:
        lines.append("- OK: no watchdog contract anomaly detected.")
    return "\n".join(lines)


__all__ = [
    "AuthoritativeCrossV1",
    "WatchdogFindingV1",
    "WatchdogInputV1",
    "WatchdogReportV1",
    "WATCHDOG_INTERVAL_SECONDS_V1",
    "ensure_runtime_watchdog_schema_v1",
    "evaluate_watchdog_contracts_v1",
    "format_watchdog_report_v1",
    "load_watchdog_findings_v1",
    "load_watchdog_report_by_id_v1",
    "load_watchdog_reports_v1",
    "load_watchdog_status_v1",
    "run_runtime_watchdog_cycle_v1",
    "run_runtime_watchdog_forever_v1",
]
