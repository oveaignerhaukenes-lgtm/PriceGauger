from __future__ import annotations

from pathlib import Path

from autotrader_mtf_flip_live_runtime_v2 import (
    REQUEST_APPROVED,
    REQUEST_PENDING,
    REQUEST_SUPERSEDED,
    _supersede_prior_execution_requests_v2,
)


def test_mtf_flip_runtime_emits_requests_but_has_no_saxo_post_authority() -> None:
    source = Path("autotrader_mtf_flip_live_runtime_v2.py").read_text(encoding="utf-8")
    assert "pg_v2_autotrader_execution_requests" in source
    assert "pg_v2_autotrader_mtf_flip_live_state" in source
    assert "pg_v2_autotrader_mtf_flip_live_events" in source
    assert "BOOTSTRAP_NO_REPLAY" in source
    assert "NEWER_MTF_FLIP_SIGNAL" in source
    assert "state.pending is not None and observed_direction == DIRECTION_FLAT" in source
    assert "_post_once" not in source
    assert "trade/v2/orders" not in source
    assert "live_open_order_payload_v2" not in source


def test_mtf_flip_carries_only_30m_reversal_and_never_one_order_reverses() -> None:
    policy = Path("autotrader_mtf_flip_policy_v2.py").read_text(encoding="utf-8")
    runtime = Path("autotrader_mtf_flip_live_runtime_v2.py").read_text(encoding="utf-8")
    assert "sole event allowed to carry a direction target across CLOSE -> FLAT -> OPEN" in policy
    assert "Fast clocks advance but cannot create a second order" in runtime
    assert 'return "CLOSE" if observed_direction != DIRECTION_FLAT else None' in runtime
    assert 'return "OPEN"' in runtime
    assert "decision.carry_reversal" in runtime
    assert "pending_target_direction TEXT CHECK (pending_target_direction IN ('LONG','SHORT'))" in runtime
    assert "trade/v2/orders" not in runtime


def test_dispatch_selects_mtf_flip_and_reuses_shared_position_snapshot() -> None:
    dispatch = Path("autotrader_automanage_dispatch_v2.py").read_text(encoding="utf-8")
    assert "MTF_LONG_SHORT_FLIP_STRATEGY_V2" in dispatch
    assert "run_mtf_flip_live_strategy_once_v2" in dispatch
    assert "observations = _position_observations_v2(client)" in dispatch
    assert "observations=observations" in dispatch


def test_mtf_flip_is_directionally_admitted_for_both_long_and_short() -> None:
    catalog = Path("autotrader_strategy_catalog_v2.py").read_text(encoding="utf-8")
    gate = Path("tradingdesk_autotrade_entry_gate_v2.py").read_text(encoding="utf-8")
    assert 'MTF_LONG_SHORT_FLIP_STRATEGY_V2 = "macd-mtf-30-10-5-long-short-v1"' in catalog
    assert "MTF_LONG_SHORT_FLIP_SPEC_V2" in catalog
    assert "can_long=True" in catalog
    assert "can_short=True" in catalog
    assert "if spec.can_long:" in gate
    assert "if spec.can_short:" in gate


class _CaptureDb:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, sql: str, params=()):
        self.calls.append((sql, tuple(params)))
        return self


def test_supersede_without_current_request_has_no_untyped_nullable_placeholder() -> None:
    db = _CaptureDb()
    _supersede_prior_execution_requests_v2(
        db,
        pilot_key="pilot-1",
        request_id=None,
    )

    assert len(db.calls) == 1
    sql, params = db.calls[0]
    assert "IS NULL" not in sql
    assert "request_id <>" not in sql
    assert params == (
        REQUEST_SUPERSEDED,
        "pilot-1",
        REQUEST_PENDING,
        REQUEST_APPROVED,
    )


def test_supersede_with_current_request_excludes_only_that_request() -> None:
    db = _CaptureDb()
    _supersede_prior_execution_requests_v2(
        db,
        pilot_key="pilot-1",
        request_id="request-1",
    )

    assert len(db.calls) == 1
    sql, params = db.calls[0]
    assert "IS NULL" not in sql
    assert "request_id <> ?" in sql
    assert params == (
        REQUEST_SUPERSEDED,
        "pilot-1",
        REQUEST_PENDING,
        REQUEST_APPROVED,
        "request-1",
    )
