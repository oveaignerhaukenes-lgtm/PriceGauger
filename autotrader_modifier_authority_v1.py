"""Explicit opt-in for automatic exits outside the selected strategy."""

from database import connect, using_postgres

MODIFIERS = ("breakeven_reset", "position_guardian", "take_profit")


def ensure_modifier_authority_v1() -> None:
    if not using_postgres():
        return
    with connect() as db:
        # Several stream workers start together; serialize the first CREATE TABLE.
        db.execute("SELECT pg_advisory_xact_lock(hashtext('pg_v2_autotrader_modifier_authority_v1'))")
        db.execute(
            """CREATE TABLE IF NOT EXISTS pg_v2_autotrader_modifier_authority (
                name TEXT PRIMARY KEY, enabled BOOLEAN NOT NULL DEFAULT FALSE,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )"""
        )
        db.execute(
            """INSERT INTO pg_v2_autotrader_modifier_authority(name, enabled)
               VALUES ('breakeven_reset', FALSE), ('position_guardian', FALSE),
                      ('take_profit', FALSE)
               ON CONFLICT (name) DO NOTHING"""
        )


def modifier_enabled_v1(name: str) -> bool:
    if name not in MODIFIERS or not using_postgres():
        return False
    ensure_modifier_authority_v1()
    with connect() as db:
        row = db.execute(
            "SELECT enabled FROM pg_v2_autotrader_modifier_authority WHERE name = ?",
            (name,),
        ).fetchone()
    return bool(row["enabled"] if isinstance(row, dict) else row[0]) if row else False


def set_modifier_enabled_v1(name: str, enabled: bool) -> None:
    if name not in MODIFIERS or not using_postgres():
        raise ValueError("Unknown modifier or PostgreSQL unavailable")
    ensure_modifier_authority_v1()
    with connect() as db:
        db.execute(
            """UPDATE pg_v2_autotrader_modifier_authority
               SET enabled = ?, updated_at = now() WHERE name = ?""",
            (bool(enabled), name),
        )
        if enabled and name in {"breakeven_reset", "position_guardian"}:
            # A previously queued exit must never fire after an opt-in.
            reasons = ("BREAKEVEN_RESET",) if name == "breakeven_reset" else (
                "HARD_STOP", "TRAILING_STOP", "FIXED_TAKE_PROFIT"
            )
            for reason in reasons:
                db.execute(
                    """UPDATE pg_v2_autotrader_risk_state
                       SET triggered_reason = NULL, triggered_at = NULL
                       WHERE triggered_reason = ?""",
                    (reason,),
                )
