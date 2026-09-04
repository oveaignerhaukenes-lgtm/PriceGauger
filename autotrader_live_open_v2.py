from __future__ import annotations

"""LIVE OPEN facade with execution/accounting decoupling.

The hardened submit/reconcile implementation remains in
``autotrader_live_open_legacy_v2`` during the bounded Simple Core migration.  This
facade changes only the FLAT-authority contract: broker-confirmed FLAT after a PG
close may re-enter before realized-P/L accounting catches up. Ambiguous SUBMITTING or
UNCERTAIN closes still block.
"""

import autotrader_live_open_legacy_v2 as _legacy
from autotrader_live_open_legacy_v2 import *  # noqa: F401,F403
from autotrader_strategy_switch_provenance_v2 import has_unconsumed_settled_flat_handoff_v2
from autotrader_trade_markers_v1 import ensure_autotrader_trade_marker_schema_v1
from database import connect


def _row_value(row, key: str, index: int):
    if isinstance(row, dict):
        return row[key]
    return row[index]


def _execution_close_provenance_v1(pilot_key: str) -> tuple[bool, bool]:
    """Return (FLAT execution authority, ambiguous close).

    P/L reconciliation is accounting and no longer sits on the critical reversal
    path. A PG close that reached ORDER_ACCEPTED or RECONCILED is sufficient execution
    provenance once the unchanged LIVE OPEN engine independently observes the exact
    Saxo product FLAT. SUBMITTING and UNCERTAIN remain ambiguous and therefore wait.
    """
    with connect() as db:
        enrollment = db.execute(
            """
            SELECT account_id, uic, asset_type, enrolled_at
            FROM pg_v2_autotrader_strategy_enrollments
            WHERE pilot_key = ? AND enabled = TRUE
            """,
            (str(pilot_key),),
        ).fetchone()
        if enrollment is None:
            return False, True
        account_id = str(_row_value(enrollment, "account_id", 0))
        uic = int(_row_value(enrollment, "uic", 1))
        asset_type = str(_row_value(enrollment, "asset_type", 2))
        enrolled_at = _row_value(enrollment, "enrolled_at", 3)

        ambiguous = db.execute(
            """
            SELECT 1
            FROM pg_v2_autotrader_live_close_attempts
            WHERE account_id = ? AND uic = ? AND asset_type = ?
              AND created_at >= ? AND status IN ('SUBMITTING', 'UNCERTAIN')
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (account_id, uic, asset_type, enrolled_at),
        ).fetchone()
        if ambiguous is not None:
            return False, True

        completed = db.execute(
            """
            SELECT 1
            FROM pg_v2_autotrader_live_close_attempts
            WHERE account_id = ? AND uic = ? AND asset_type = ?
              AND created_at >= ? AND status IN ('ORDER_ACCEPTED', 'RECONCILED')
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (account_id, uic, asset_type, enrolled_at),
        ).fetchone()

    if completed is not None:
        return True, False

    handoff = has_unconsumed_settled_flat_handoff_v2(
        pilot_key=str(pilot_key),
        enrolled_at=_legacy._utc(enrolled_at),
    )
    return bool(handoff), False


# Patch only the provenance helper used by the preserved hardened loop. Everything
# after it still verifies exact Saxo FLAT, working orders, current authority, sizing,
# final precheck and durable-attempt-before-POST exactly as before.
_legacy._settled_close_provenance = _execution_close_provenance_v1
_settled_close_provenance = _execution_close_provenance_v1


def run_live_open_forever_v2(*, interval_seconds: int = 2) -> None:
    """Install the observational marker projection before entering the hardened loop."""
    ensure_autotrader_trade_marker_schema_v1()
    _legacy.run_live_open_forever_v2(interval_seconds=interval_seconds)


__all__ = list(_legacy.__all__)
