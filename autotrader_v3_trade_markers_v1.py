from __future__ import annotations

"""Read-only V3 execution provenance for TradingDesk chart markers.

The V3 order guard is the durable execution/reconciliation source of truth. During
the multi-instance migration the current production V3 identity still lives in the
strategy-enrollment boundary, so use that exact account/UIC/asset mapping for chart
projection. The registry can replace this compatibility join once the runtime cutover
bootstraps every production instance.
"""

from autotrader_trade_markers_v1 import AutoTraderTradeMarkerV1
from database import connect, using_postgres


def load_v3_trade_markers_v1(market_name: str) -> tuple[AutoTraderTradeMarkerV1, ...]:
    if not using_postgres():
        return ()
    try:
        with connect() as db:
            rows = db.execute(
                """
                SELECT guard.updated_at AS executed_at,
                       nearest_bar.close AS execution_price,
                       guard.submitted_side,
                       guard.submitted_amount,
                       guard.request_key,
                       guard.trader_id,
                       guard.expected_inventory
                FROM autotrader_v3_order_guard AS guard
                JOIN pg_v2_autotrader_strategy_enrollments AS enrollment
                  ON enrollment.pilot_key = guard.trader_id
                 AND enrollment.account_id = guard.account_id
                 AND enrollment.uic = guard.uic
                 AND enrollment.asset_type = guard.asset_type
                JOIN LATERAL (
                    SELECT bar.close
                    FROM pg_v2_market_bars_1m AS bar
                    WHERE bar.instrument_id = enrollment.instrument_id
                      AND bar.bar_time BETWEEN guard.updated_at::timestamptz - INTERVAL '10 minutes'
                                           AND guard.updated_at::timestamptz + INTERVAL '10 minutes'
                    ORDER BY ABS(EXTRACT(EPOCH FROM (bar.bar_time - guard.updated_at::timestamptz)))
                    LIMIT 1
                ) AS nearest_bar ON TRUE
                WHERE enrollment.market_name = ?
                  AND guard.state = 'RECONCILED'
                  AND guard.submitted_amount > 0
                  AND lower(guard.submitted_side) IN ('buy','sell')
                  AND guard.updated_at::timestamptz >= now() - INTERVAL '14 days'
                ORDER BY guard.updated_at::timestamptz ASC
                LIMIT 1000
                """,
                (str(market_name),),
            ).fetchall()
    except Exception:
        return ()

    result: list[AutoTraderTradeMarkerV1] = []
    for row in rows:
        value = dict(row) if isinstance(row, dict) else {
            "executed_at": row[0], "execution_price": row[1], "submitted_side": row[2],
            "submitted_amount": row[3], "request_key": row[4], "trader_id": row[5],
            "expected_inventory": row[6],
        }
        expected = value.get("expected_inventory")
        direction = "FLAT" if expected is not None and abs(float(expected)) <= 1e-9 else (
            "LONG" if str(value["submitted_side"]).lower() == "buy" else "SHORT"
        )
        result.append(
            AutoTraderTradeMarkerV1(
                executed_at=value["executed_at"],
                execution_price=float(value["execution_price"]),
                direction=direction,
                amount=float(value["submitted_amount"]),
                strategy_key=str(value["trader_id"]),
                net_position_id=str(value["request_key"]),
                active=False,
                source="AUTOTRADER_V3",
            )
        )
    return tuple(result)


__all__ = ["load_v3_trade_markers_v1"]
