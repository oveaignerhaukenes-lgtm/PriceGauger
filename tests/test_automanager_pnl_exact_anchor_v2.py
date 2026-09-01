from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

import autotrader_shadow_benchmark_exact_anchor_v2 as exact
from autotrader_strategy_enrollment_v2 import EXECUTION_MODE_LIVE, StrategyEnrollmentV2


def _enrollment(*, pilot_key: str = "pilot-live") -> StrategyEnrollmentV2:
    return StrategyEnrollmentV2(
        pilot_key=pilot_key,
        strategy_key="macd-30m-long-flat-v1",
        execution_mode=EXECUTION_MODE_LIVE,
        account_id="acct-1",
        anchor_net_position_id="anchor-123",
        uic=4912,
        asset_type="CfdOnIndex",
        market_id=1,
        instrument_id=2,
        market_name="US Tech 100 NAS · Saxo 4912",
        enabled=False,
        live_open_armed=False,
        entry_mode="AUTO",
    )


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class _Db:
    def execute(self, sql, params=()):
        if "FROM pg_v2_autotrader_strategy_enrollments" in sql:
            return _Rows([
                {"enrolled_at": datetime(2026, 9, 1, 6, 0, tzinfo=timezone.utc)},
            ])
        if "FROM pg_v2_autotrader_managed_positions" in sql:
            assert params == ("acct-1", "anchor-123", 4912, "CfdOnIndex")
            # Deliberately hours away. Exact identity, not timestamp proximity, is authority.
            return _Rows([
                {
                    "net_position_id": "anchor-123",
                    "direction": "buy",
                    "enrolled_at": datetime(2026, 8, 31, 18, 0, tzinfo=timezone.utc),
                }
            ])
        raise AssertionError(sql)


@contextmanager
def _connect():
    yield _Db()


def test_exact_anchor_uses_persisted_position_id_not_timestamp_distance(monkeypatch):
    monkeypatch.setattr(exact, "connect", _connect)

    started_at, initial_state, position_id = exact._exact_anchor((_enrollment(),))

    assert started_at == datetime(2026, 9, 1, 6, 0, tzinfo=timezone.utc)
    assert initial_state == "LONG"
    assert position_id == "anchor-123"


def test_pnl_comparison_routes_through_exact_anchor_loader():
    source = open("autotrader_pnl_comparison_v2.py", encoding="utf-8").read()
    assert "load_shadow_benchmark_series_exact_anchor_v2" in source
    assert "load_shadow_benchmark_series_v2(" not in source
