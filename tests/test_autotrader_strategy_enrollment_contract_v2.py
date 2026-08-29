from __future__ import annotations

from types import SimpleNamespace

import pytest

import autotrader_strategy_enrollment_v2 as enrollment_v2


class _Product:
    account_id = "acct-1"
    anchor_position_id = "position-1"
    provider_instrument_id = "4912"
    asset_type = "CfdOnIndex"
    market_id = 17
    instrument_id = 23
    market_name = "sp500 CFD"

    def pilot_key(self, strategy_key: str) -> str:
        return f"pilot:{strategy_key}"


def test_second_live_controller_is_blocked_before_side_effects(monkeypatch):
    monkeypatch.setattr(enrollment_v2, "ensure_autotrader_schema_v2", lambda: None)
    monkeypatch.setattr(enrollment_v2, "strategy_spec_v2", lambda _strategy_key: None)
    monkeypatch.setattr(enrollment_v2, "resolve_saxo_automanage_product_v2", lambda _observation: _Product())
    monkeypatch.setattr(
        enrollment_v2,
        "load_product_strategy_enrollments_v2",
        lambda **_kwargs: (
            SimpleNamespace(
                execution_mode=enrollment_v2.EXECUTION_MODE_LIVE,
                pilot_key="pilot:already-live",
                strategy_key="macd-30m-long-flat-v1",
            ),
        ),
    )

    side_effects: list[str] = []
    monkeypatch.setattr(
        enrollment_v2,
        "initialize_pilot_equity_v2",
        lambda **_kwargs: side_effects.append("equity"),
    )
    monkeypatch.setattr(
        enrollment_v2,
        "enroll_position_v1",
        lambda _observation: side_effects.append("managed-position"),
    )

    with pytest.raises(ValueError, match="already has an active LIVE AutoManage controller"):
        enrollment_v2.enroll_strategy_position_v2(
            object(),
            strategy_key="macd-30m-short-flat-v1",
            execution_mode=enrollment_v2.EXECUTION_MODE_LIVE,
        )

    assert side_effects == []


def test_shadow_strategy_remains_allowed_alongside_live_controller(monkeypatch):
    monkeypatch.setattr(enrollment_v2, "ensure_autotrader_schema_v2", lambda: None)
    monkeypatch.setattr(enrollment_v2, "strategy_spec_v2", lambda _strategy_key: None)
    monkeypatch.setattr(enrollment_v2, "resolve_saxo_automanage_product_v2", lambda _observation: _Product())

    def _unexpected_lookup(**_kwargs):
        raise AssertionError("shadow enrollment must not consult LIVE-controller preflight")

    monkeypatch.setattr(enrollment_v2, "load_product_strategy_enrollments_v2", _unexpected_lookup)

    ledger = object()
    monkeypatch.setattr(enrollment_v2, "initialize_pilot_equity_v2", lambda **_kwargs: ledger)
    monkeypatch.setattr(enrollment_v2, "enroll_position_v1", lambda _observation: pytest.fail("shadow must not enroll a managed LIVE position"))

    executed: list[tuple[str, tuple[object, ...]]] = []

    class _Db:
        def execute(self, sql, params=()):
            executed.append((sql, tuple(params)))
            return self

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(enrollment_v2, "connect", lambda: _Db())
    expected = SimpleNamespace(pilot_key="pilot:macd-30m-short-flat-v1")
    monkeypatch.setattr(enrollment_v2, "load_strategy_enrollment_v2", lambda _pilot_key: expected)

    result, returned_ledger = enrollment_v2.enroll_strategy_position_v2(
        object(),
        strategy_key="macd-30m-short-flat-v1",
        execution_mode=enrollment_v2.EXECUTION_MODE_SHADOW,
        entry_mode=enrollment_v2.ENTRY_MODE_AUTO,
    )

    assert result is expected
    assert returned_ledger is ledger
    assert executed
    assert enrollment_v2.EXECUTION_MODE_SHADOW in executed[0][1]
    assert enrollment_v2.ENTRY_MODE_MANUAL_ONLY in executed[0][1]
