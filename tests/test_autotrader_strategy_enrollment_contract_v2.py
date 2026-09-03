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


class _Db:
    def __init__(self, executed):
        self.executed = executed

    def execute(self, sql, params=()):
        self.executed.append((sql, tuple(params)))
        return self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


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
    monkeypatch.setattr(enrollment_v2, "connect", lambda: _Db(executed))
    expected = SimpleNamespace(pilot_key="pilot:macd-30m-short-flat-v1", enabled=True)
    monkeypatch.setattr(enrollment_v2, "load_strategy_enrollment_v2", lambda _pilot_key: None if not executed else expected)

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


def test_disabled_canonical_live_pilot_resumes_existing_equity_and_entry_mode(monkeypatch):
    monkeypatch.setattr(enrollment_v2, "ensure_autotrader_schema_v2", lambda: None)
    monkeypatch.setattr(enrollment_v2, "strategy_spec_v2", lambda _strategy_key: None)
    monkeypatch.setattr(enrollment_v2, "resolve_saxo_automanage_product_v2", lambda _observation: _Product())
    monkeypatch.setattr(enrollment_v2, "load_product_strategy_enrollments_v2", lambda **_kwargs: ())

    strategy_key = "macd-mtf-30-10-5-long-short-v1"
    pilot_key = f"pilot:{strategy_key}"
    disabled = SimpleNamespace(
        pilot_key=pilot_key,
        strategy_key=strategy_key,
        execution_mode=enrollment_v2.EXECUTION_MODE_LIVE,
        enabled=False,
        entry_mode=enrollment_v2.ENTRY_MODE_AUTO,
    )
    resumed = SimpleNamespace(
        pilot_key=pilot_key,
        strategy_key=strategy_key,
        execution_mode=enrollment_v2.EXECUTION_MODE_LIVE,
        enabled=True,
        entry_mode=enrollment_v2.ENTRY_MODE_AUTO,
        live_open_armed=True,
    )
    executed: list[tuple[str, tuple[object, ...]]] = []
    lookups = {"count": 0}

    def _load(_pilot_key):
        lookups["count"] += 1
        return disabled if lookups["count"] == 1 else resumed

    monkeypatch.setattr(enrollment_v2, "load_strategy_enrollment_v2", _load)
    ledger = SimpleNamespace(seed_capital=594.57, currency="NOK", realized_net_pnl=0.0, equity=594.57)
    monkeypatch.setattr(enrollment_v2, "load_pilot_equity_v2", lambda **_kwargs: ledger)
    monkeypatch.setattr(
        enrollment_v2,
        "initialize_pilot_equity_v2",
        lambda **_kwargs: pytest.fail("resume must never reinitialize or compare the caller's seed"),
    )
    managed: list[object] = []
    monkeypatch.setattr(enrollment_v2, "enroll_position_v1", lambda observation: managed.append(observation))
    monkeypatch.setattr(enrollment_v2, "connect", lambda: _Db(executed))

    observation = object()
    result, returned_ledger = enrollment_v2.enroll_strategy_position_v2(
        observation,
        strategy_key=strategy_key,
        execution_mode=enrollment_v2.EXECUTION_MODE_LIVE,
        seed_capital=500.0,
        currency="NOK",
        entry_mode=enrollment_v2.ENTRY_MODE_MANUAL_ONLY,
    )

    assert result is resumed
    assert returned_ledger is ledger
    assert managed == [observation]
    assert executed
    sql, params = executed[0]
    assert "live_open_armed=EXCLUDED.live_open_armed" in sql
    assert "enrolled_at=now()" not in sql.split("ON CONFLICT", 1)[1]
    assert True in params
    assert enrollment_v2.ENTRY_MODE_AUTO in params


def test_set_entry_mode_auto_arms_open_and_other_modes_disarm(monkeypatch):
    monkeypatch.setattr(enrollment_v2, "ensure_autotrader_schema_v2", lambda: None)
    active = SimpleNamespace(enabled=True, execution_mode=enrollment_v2.EXECUTION_MODE_LIVE)
    refreshed = SimpleNamespace(enabled=True, execution_mode=enrollment_v2.EXECUTION_MODE_LIVE)
    lookups = {"count": 0}

    def _load(_pilot_key):
        lookups["count"] += 1
        return active if lookups["count"] == 1 else refreshed

    monkeypatch.setattr(enrollment_v2, "load_strategy_enrollment_v2", _load)
    executed: list[tuple[str, tuple[object, ...]]] = []
    monkeypatch.setattr(enrollment_v2, "connect", lambda: _Db(executed))

    assert enrollment_v2.set_entry_mode_v2("pilot", enrollment_v2.ENTRY_MODE_AUTO) is refreshed
    assert executed[-1][1][0] == enrollment_v2.ENTRY_MODE_AUTO
    assert executed[-1][1][1] is True

    lookups["count"] = 0
    assert enrollment_v2.set_entry_mode_v2("pilot", enrollment_v2.ENTRY_MODE_MANUAL_ONLY) is refreshed
    assert executed[-1][1][0] == enrollment_v2.ENTRY_MODE_MANUAL_ONLY
    assert executed[-1][1][1] is False


def test_resume_rejects_currency_change(monkeypatch):
    monkeypatch.setattr(enrollment_v2, "ensure_autotrader_schema_v2", lambda: None)
    monkeypatch.setattr(enrollment_v2, "strategy_spec_v2", lambda _strategy_key: None)
    monkeypatch.setattr(enrollment_v2, "resolve_saxo_automanage_product_v2", lambda _observation: _Product())
    monkeypatch.setattr(enrollment_v2, "load_product_strategy_enrollments_v2", lambda **_kwargs: ())

    strategy_key = "macd-mtf-30-10-5-long-short-v1"
    monkeypatch.setattr(
        enrollment_v2,
        "load_strategy_enrollment_v2",
        lambda _pilot_key: SimpleNamespace(
            strategy_key=strategy_key,
            execution_mode=enrollment_v2.EXECUTION_MODE_LIVE,
            enabled=False,
            entry_mode=enrollment_v2.ENTRY_MODE_AUTO,
        ),
    )
    monkeypatch.setattr(
        enrollment_v2,
        "load_pilot_equity_v2",
        lambda **_kwargs: SimpleNamespace(seed_capital=594.57, currency="NOK"),
    )

    with pytest.raises(ValueError, match="currency does not match"):
        enrollment_v2.enroll_strategy_position_v2(
            object(),
            strategy_key=strategy_key,
            execution_mode=enrollment_v2.EXECUTION_MODE_LIVE,
            seed_capital=500.0,
            currency="USD",
        )