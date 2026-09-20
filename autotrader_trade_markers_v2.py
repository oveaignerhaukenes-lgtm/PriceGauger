from __future__ import annotations

from autotrader_trade_markers_v1 import AutoTraderTradeMarkerV1, load_autotrader_trade_markers_v1
from database import connect, using_postgres
from manual_saxo_trade_markers_v1 import load_manual_saxo_trade_markers_v1


def _flat_markers_v2(market_name: str) -> tuple[AutoTraderTradeMarkerV1, ...]:
    """Project reconciled PG CLOSE requests as neutral FLAT chart markers.

    CLOSE attempts do not persist an execution price.  For presentation only, anchor
    the square to the nearest canonical 1m close within ten minutes of confirmed FLAT.
    This never participates in execution, P/L accounting, or strategy state.
    """
    if not using_postgres():
        return ()
    try:
        with connect() as db:
            rows = db.execute(
                """
                SELECT close_attempt.updated_at AS executed_at,
                       nearest_bar.close AS execution_price,
                       close_attempt.amount,
                       req.strategy_key,
                       close_attempt.net_position_id
                FROM pg_v2_autotrader_live_close_attempts AS close_attempt
                JOIN pg_v2_autotrader_execution_requests AS req
                  ON req.request_id = close_attempt.event_id
                JOIN pg_v2_autotrader_strategy_enrollments AS enrollment
                  ON enrollment.pilot_key = req.pilot_key
                JOIN LATERAL (
                    SELECT bar.close
                    FROM pg_v2_market_bars_1m AS bar
                    WHERE bar.instrument_id = req.instrument_id
                      AND bar.bar_time BETWEEN close_attempt.updated_at - INTERVAL '10 minutes'
                                           AND close_attempt.updated_at + INTERVAL '10 minutes'
                    ORDER BY ABS(EXTRACT(EPOCH FROM (bar.bar_time - close_attempt.updated_at)))
                    LIMIT 1
                ) AS nearest_bar ON TRUE
                WHERE enrollment.market_name = ?
                  AND req.action = 'CLOSE'
                  AND close_attempt.status = 'RECONCILED'
                  AND close_attempt.updated_at >= now() - INTERVAL '14 days'
                ORDER BY close_attempt.updated_at ASC
                LIMIT 500
                """,
                (str(market_name),),
            ).fetchall()
    except Exception:
        return ()

    result: list[AutoTraderTradeMarkerV1] = []
    for row in rows:
        value = dict(row) if isinstance(row, dict) else {
            "executed_at": row[0],
            "execution_price": row[1],
            "amount": row[2],
            "strategy_key": row[3],
            "net_position_id": row[4],
        }
        result.append(
            AutoTraderTradeMarkerV1(
                executed_at=value["executed_at"],
                execution_price=float(value["execution_price"]),
                direction="FLAT",
                amount=float(value["amount"]),
                strategy_key=str(value["strategy_key"] or ""),
                net_position_id=str(value["net_position_id"] or ""),
                active=False,
                source="AUTOTRADER_CLOSE_CONFIRMED",
            )
        )
    return tuple(result)


def load_autotrader_trade_markers_v2(market_name: str) -> tuple[AutoTraderTradeMarkerV1, ...]:
    markers = list(load_autotrader_trade_markers_v1(market_name))
    markers.extend(_flat_markers_v2(market_name))
    markers.extend(load_manual_saxo_trade_markers_v1(market_name))
    markers.sort(key=lambda item: (item.executed_at, item.direction, item.net_position_id))
    return tuple(markers)


__all__ = ["load_autotrader_trade_markers_v2"]
