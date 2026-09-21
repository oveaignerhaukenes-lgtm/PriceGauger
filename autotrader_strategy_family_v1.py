from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

from database import connect, using_postgres


FAMILY_MACD_V1 = "MACD"
FAMILY_PRICE_MACD_V1 = "PRICE_MACD"
FAMILY_PRICE_STOCH_V1 = "PRICE_STOCH"

FAMILY_MACD_STRATEGY_V1 = "family-macd-v1"
FAMILY_PRICE_MACD_STRATEGY_V1 = "family-price-macd-v1"
FAMILY_PRICE_STOCH_STRATEGY_V1 = "price-stoch-half-parade-v1"

FAMILY_LABELS_V1 = {
    FAMILY_MACD_V1: "MACD",
    FAMILY_PRICE_MACD_V1: "Price + MACD",
    FAMILY_PRICE_STOCH_V1: "Price + Stoch",
}
FAMILY_TO_STRATEGY_KEY_V1 = {
    FAMILY_MACD_V1: FAMILY_MACD_STRATEGY_V1,
    FAMILY_PRICE_MACD_V1: FAMILY_PRICE_MACD_STRATEGY_V1,
    FAMILY_PRICE_STOCH_V1: FAMILY_PRICE_STOCH_STRATEGY_V1,
}
STRATEGY_KEY_TO_FAMILY_V1 = {value: key for key, value in FAMILY_TO_STRATEGY_KEY_V1.items()}

TIMEFRAME_PRESETS_V1 = (1, 2, 5, 10, 15, 30, 60)
MIN_TIMEFRAME_MINUTES_V1 = 1
MAX_TIMEFRAME_MINUTES_V1 = 240

_SCHEMA_LOCK = Lock()
_SCHEMA_READY = False


@dataclass(frozen=True, slots=True)
class StrategyFamilyConfigV1:
    pilot_key: str
    family: str
    timeframe_minutes: int


def validate_timeframe_minutes_v1(value: int) -> int:
    minutes = int(value)
    if not MIN_TIMEFRAME_MINUTES_V1 <= minutes <= MAX_TIMEFRAME_MINUTES_V1:
        raise ValueError(
            f"timeframe must be {MIN_TIMEFRAME_MINUTES_V1}-{MAX_TIMEFRAME_MINUTES_V1} minutes"
        )
    return minutes


def family_strategy_key_v1(family: str) -> str:
    key = str(family).strip().upper()
    try:
        return FAMILY_TO_STRATEGY_KEY_V1[key]
    except KeyError as exc:
        raise ValueError(f"unsupported strategy family: {family}") from exc


def strategy_family_v1(strategy_key: str) -> str | None:
    return STRATEGY_KEY_TO_FAMILY_V1.get(str(strategy_key))


def ensure_strategy_family_schema_v1() -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    if not using_postgres():
        raise RuntimeError("strategy family configuration requires PostgreSQL")
    with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            return
        with connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS pg_v2_autotrader_strategy_family_config (
                    pilot_key TEXT PRIMARY KEY
                        REFERENCES pg_v2_autotrader_strategy_enrollments(pilot_key),
                    family TEXT NOT NULL
                        CHECK (family IN ('MACD','PRICE_MACD','PRICE_STOCH')),
                    timeframe_minutes INTEGER NOT NULL
                        CHECK (timeframe_minutes >= 1 AND timeframe_minutes <= 240),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
        _SCHEMA_READY = True


def default_family_config_v1(
    *,
    pilot_key: str,
    strategy_key: str,
) -> StrategyFamilyConfigV1 | None:
    family = strategy_family_v1(strategy_key)
    if family is None:
        return None
    default_minutes = 1 if family in {FAMILY_PRICE_MACD_V1, FAMILY_PRICE_STOCH_V1} else 5
    return StrategyFamilyConfigV1(
        pilot_key=str(pilot_key),
        family=family,
        timeframe_minutes=default_minutes,
    )


def load_strategy_family_config_v1(
    pilot_key: str,
    *,
    strategy_key: str | None = None,
) -> StrategyFamilyConfigV1 | None:
    ensure_strategy_family_schema_v1()
    with connect() as db:
        row = db.execute(
            """
            SELECT pilot_key, family, timeframe_minutes
            FROM pg_v2_autotrader_strategy_family_config
            WHERE pilot_key = ?
            """,
            (str(pilot_key),),
        ).fetchone()
    if row is None:
        if strategy_key is None:
            return None
        return default_family_config_v1(
            pilot_key=str(pilot_key),
            strategy_key=str(strategy_key),
        )
    values = dict(row) if isinstance(row, dict) else {
        "pilot_key": row[0],
        "family": row[1],
        "timeframe_minutes": row[2],
    }
    return StrategyFamilyConfigV1(
        pilot_key=str(values["pilot_key"]),
        family=str(values["family"]),
        timeframe_minutes=validate_timeframe_minutes_v1(int(values["timeframe_minutes"])),
    )


def save_strategy_family_config_v1(
    *,
    pilot_key: str,
    family: str,
    timeframe_minutes: int,
) -> StrategyFamilyConfigV1:
    normalized_family = str(family).strip().upper()
    strategy_key = family_strategy_key_v1(normalized_family)
    minutes = validate_timeframe_minutes_v1(timeframe_minutes)
    ensure_strategy_family_schema_v1()
    with connect() as db:
        enrollment = db.execute(
            """
            SELECT strategy_key
            FROM pg_v2_autotrader_strategy_enrollments
            WHERE pilot_key = ?
            """,
            (str(pilot_key),),
        ).fetchone()
        if enrollment is None:
            raise LookupError("strategy enrollment not found for family configuration")
        current_key = str(
            enrollment["strategy_key"] if isinstance(enrollment, dict) else enrollment[0]
        )
        if current_key != strategy_key:
            raise ValueError(
                f"family config {normalized_family} does not match enrolled strategy {current_key}"
            )
        db.execute(
            """
            INSERT INTO pg_v2_autotrader_strategy_family_config(
                pilot_key, family, timeframe_minutes, updated_at
            ) VALUES (?, ?, ?, now())
            ON CONFLICT (pilot_key) DO UPDATE SET
                family=EXCLUDED.family,
                timeframe_minutes=EXCLUDED.timeframe_minutes,
                updated_at=now()
            """,
            (str(pilot_key), normalized_family, minutes),
        )
    return StrategyFamilyConfigV1(
        pilot_key=str(pilot_key),
        family=normalized_family,
        timeframe_minutes=minutes,
    )


def reconfigure_live_family_v1(
    *,
    pilot_key: str,
    family: str,
    timeframe_minutes: int,
) -> StrategyFamilyConfigV1:
    """Change family parameters without replaying stale signal authority.

    The product/strategy enrollment remains unchanged. Only unstarted strategy
    requests are superseded; any broker-ambiguous execution blocks reconfiguration.
    Runtime state is cleared so the next cycle bootstraps from observed Saxo exposure.
    """

    normalized_family = str(family).strip().upper()
    expected_strategy_key = family_strategy_key_v1(normalized_family)
    minutes = validate_timeframe_minutes_v1(timeframe_minutes)
    ensure_strategy_family_schema_v1()
    with connect() as db:
        enrollment = db.execute(
            """
            SELECT strategy_key, execution_mode, enabled
            FROM pg_v2_autotrader_strategy_enrollments
            WHERE pilot_key = ?
            """,
            (str(pilot_key),),
        ).fetchone()
        if enrollment is None:
            raise LookupError("active family enrollment not found")
        values = dict(enrollment) if isinstance(enrollment, dict) else {
            "strategy_key": enrollment[0],
            "execution_mode": enrollment[1],
            "enabled": enrollment[2],
        }
        if not bool(values["enabled"]) or str(values["execution_mode"]) != "LIVE_MANAGE":
            raise ValueError("family reconfiguration requires an active LIVE enrollment")
        if str(values["strategy_key"]) != expected_strategy_key:
            raise ValueError("family reconfiguration does not match active strategy")

        inflight = db.execute(
            """
            SELECT 1
            FROM pg_v2_autotrader_execution_requests
            WHERE pilot_key = ?
              AND status IN ('SUBMITTING','ORDER_ACCEPTED','UNCERTAIN')
            LIMIT 1
            """,
            (str(pilot_key),),
        ).fetchone()
        if inflight is not None:
            raise ValueError("timeframe change waits while execution is in flight")

        db.execute(
            """
            UPDATE pg_v2_autotrader_execution_requests
            SET status='SUPERSEDED', block_reason='FAMILY_PARAMETER_CHANGE', updated_at=now()
            WHERE pilot_key = ? AND status IN ('PENDING','APPROVED')
            """,
            (str(pilot_key),),
        )
        db.execute(
            "DELETE FROM pg_v2_autotrader_fast_live_state WHERE pilot_key = ?",
            (str(pilot_key),),
        )
        db.execute(
            """
            INSERT INTO pg_v2_autotrader_strategy_family_config(
                pilot_key, family, timeframe_minutes, updated_at
            ) VALUES (?, ?, ?, now())
            ON CONFLICT (pilot_key) DO UPDATE SET
                family=EXCLUDED.family,
                timeframe_minutes=EXCLUDED.timeframe_minutes,
                updated_at=now()
            """,
            (str(pilot_key), normalized_family, minutes),
        )
    return StrategyFamilyConfigV1(
        pilot_key=str(pilot_key),
        family=normalized_family,
        timeframe_minutes=minutes,
    )


def family_display_label_v1(family: str, timeframe_minutes: int) -> str:
    normalized = str(family).strip().upper()
    label = FAMILY_LABELS_V1.get(normalized, normalized)
    return f"{label} · {validate_timeframe_minutes_v1(timeframe_minutes)}m"


__all__ = [
    "FAMILY_LABELS_V1",
    "FAMILY_MACD_STRATEGY_V1",
    "FAMILY_MACD_V1",
    "FAMILY_PRICE_MACD_STRATEGY_V1",
    "FAMILY_PRICE_MACD_V1",
    "FAMILY_PRICE_STOCH_STRATEGY_V1",
    "FAMILY_PRICE_STOCH_V1",
    "FAMILY_TO_STRATEGY_KEY_V1",
    "MAX_TIMEFRAME_MINUTES_V1",
    "MIN_TIMEFRAME_MINUTES_V1",
    "STRATEGY_KEY_TO_FAMILY_V1",
    "StrategyFamilyConfigV1",
    "TIMEFRAME_PRESETS_V1",
    "default_family_config_v1",
    "ensure_strategy_family_schema_v1",
    "family_display_label_v1",
    "family_strategy_key_v1",
    "load_strategy_family_config_v1",
    "reconfigure_live_family_v1",
    "save_strategy_family_config_v1",
    "strategy_family_v1",
    "validate_timeframe_minutes_v1",
]
