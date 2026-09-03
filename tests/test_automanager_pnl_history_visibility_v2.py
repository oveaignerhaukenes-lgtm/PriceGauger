from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import autotrader_shadow_benchmark_v2 as benchmark
from autotrader_strategy_enrollment_v2 import StrategyEnrollmentV2


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeDb:
    def __init__(self):
        self.queries: list[tuple[str, tuple]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=()):
        normalized = " ".join(str(sql).split())
        self.queries.append((normalized, tuple(params)))
        if "FROM pg_v2_autotrader_strategy_enrollments" in normalized:
            return _Rows([{"enrolled_at": datetime(2026, 8, 31, 18, 0, tzinfo=timezone.utc)}])
        if "FROM pg_v2_autotrader_managed_positions" in normalized:
            return _Rows(
                [
                    {
                        "net_position_id": "position-1",
                        "direction": "Buy",
                        # Deliberately far from strategy enrollment. Exact persisted
                        # position identity, not timestamp proximity, is authoritative.
                        "enrolled_at": datetime(2026, 9, 3, 18, 0, tzinfo=timezone.utc),
                    }
                ]
            )
        raise AssertionError(normalized)


def _inactive_live_enrollment() -> StrategyEnrollmentV2:
    return StrategyEnrollmentV2(
        pilot_key="pilot-history",
        strategy_key="macd-30m-long-flat-v1",
        execution_mode="LIVE_MANAGE",
        account_id="account",
        anchor_net_position_id="position-1",
        uic=4912,
        asset_type="CfdOnIndex",
        market_id=7,
        instrument_id=11,
        market_name="US Tech 100 NAS · Saxo 4912",
        enabled=False,
        live_open_armed=False,
        entry_mode="MANUAL_ENTRY_ONLY",
    )


def test_shadow_anchor_uses_exact_persisted_position_even_when_timestamps_are_far_apart(monkeypatch):
    db = _FakeDb()
    monkeypatch.setattr(benchmark, "connect", lambda: db)

    anchor = benchmark._load_product_anchor_v2((_inactive_live_enrollment(),))

    assert anchor.managed_position_id == "position-1"
    assert anchor.initial_state == benchmark.STATE_LONG
    assert anchor.started_at == datetime(2026, 8, 31, 18, 0, tzinfo=timezone.utc)

    strategy_sql, strategy_params = db.queries[0]
    assert "WHERE pilot_key = ?" in strategy_sql
    assert "enabled = TRUE" not in strategy_sql
    assert strategy_params == ("pilot-history",)

    managed_sql, managed_params = db.queries[1]
    assert "net_position_id = ?" in managed_sql
    assert managed_params == ("account", "position-1", 4912, "CfdOnIndex")


def test_tradingdesk_pnl_has_read_only_latest_pilot_fallback_and_no_silent_disappearance():
    source = Path("tradingdesk_automanage_panel_v2.py").read_text(encoding="utf-8")

    assert "def _pnl_enrollments_for_context_v2" in source
    assert "ORDER BY updated_at DESC, enrolled_at DESC" in source
    assert "historical_fallback" in source
    assert "Ingen aktiv execution-authority gjenopprettes av grafen" in source
    assert "P/L-graf: ingen AutoManager-pilot finnes ennå for dette markedet." in source
    assert "if live is not None and live.enabled" in source
