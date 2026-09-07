from __future__ import annotations

"""LIVE OPEN facade with execution/accounting decoupling and provenance guards.

The hardened submit/reconcile implementation remains in
``autotrader_live_open_legacy_v2`` during the bounded Simple Core migration. This
facade changes the FLAT-authority contract and installs the execution-safety guard
that prevents stale broker working orders and unexplained late fills from silently
becoming fresh AutoManager authority.
"""

from typing import Mapping

import autotrader_execution_guard_v1 as _guard
import autotrader_live_open_legacy_v2 as _legacy
from autotrader_execution_guard_v1 import install_execution_safety_guard_v1
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


def _saxo_quote_error_code_v1(value: object) -> str:
    """Normalize Saxo's explicit no-error sentinels without weakening market-open checks."""
    text = str(value or "").strip()
    if text.lower() in {"", "none", "null"}:
        return ""
    return text


def _require_market_open_for_open_v1(client, *, account_id: str, uic: int, asset_type: str) -> None:
    """#322 market-open guard with Saxo's string ``None`` quote sentinel normalized."""
    _, id_to_key = _guard._accounts(client)
    account_key = id_to_key.get(account_id)
    if not account_key:
        raise ValueError("MARKET_OPEN_PRECHECK_ACCOUNT_UNRESOLVED")
    payload = client._get(
        "trade/v1/infoprices",
        params={
            "AccountKey": account_key,
            "Uic": int(uic),
            "AssetType": asset_type,
            "FieldGroups": "InstrumentPriceDetails,Quote",
        },
    )
    details = payload.get("InstrumentPriceDetails") if isinstance(payload.get("InstrumentPriceDetails"), Mapping) else {}
    quote = payload.get("Quote") if isinstance(payload.get("Quote"), Mapping) else {}
    if details.get("IsMarketOpen") is not True:
        raise ValueError("SAXO_MARKET_NOT_EXPLICITLY_OPEN")
    error_code = _saxo_quote_error_code_v1(quote.get("ErrorCode"))
    if error_code:
        raise ValueError(f"SAXO_MARKET_QUOTE_ERROR:{error_code}")


# Keep the preserved executor, but install explicit safety boundaries around its
# broker working-order, submit and adoption edges before any runtime thread starts.
# Saxo currently returns Quote.ErrorCode="None" for a valid quote. The original
# #322 guard treated that non-empty string as an error; replace only that validation
# function while preserving the explicit IsMarketOpen=True requirement.
_guard.require_market_open_for_open_v1 = _require_market_open_for_open_v1
install_execution_safety_guard_v1()
_legacy._settled_close_provenance = _execution_close_provenance_v1
_settled_close_provenance = _execution_close_provenance_v1


def run_live_open_forever_v2(*, interval_seconds: int = 2) -> None:
    """Install observational marker projection before entering the guarded loop."""
    ensure_autotrader_trade_marker_schema_v1()
    _legacy.run_live_open_forever_v2(interval_seconds=interval_seconds)


__all__ = list(_legacy.__all__)
