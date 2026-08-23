from __future__ import annotations

import autotrader_live_close_v1 as close
from autotrader_risk_dry_run_v2 import PositionObservationV2


def _obs(*, direction: str = "Buy", amount: float = 2.0) -> PositionObservationV2:
    return PositionObservationV2(
        account_id="A1",
        net_position_id="NP1",
        uic=42,
        asset_type="Stock",
        direction=direction,
        amount=amount,
        average_open_price=100.0,
        current_price=99.0,
        pnl_pct=-1.0 if direction == "Buy" else 1.0,
        price_delay_minutes=0,
        can_be_closed=True,
        calculation_reliability="Ok",
        is_market_open=True,
        non_tradable_reason="None",
    )


def test_close_payload_is_automatic_reduce_only_market_order() -> None:
    payload = close._close_payload(
        account_key="KEY",
        observation=_obs(direction="Buy"),
        external_reference="pg-close-test",
    )
    assert payload["BuySell"] == "Sell"
    assert payload["Amount"] == 2.0
    assert payload["ManualOrder"] is False
    assert payload["IsForceOpen"] is False
    assert payload["OrderType"] == "Market"
    assert payload["OrderDuration"] == {"DurationType": "DayOrder"}


def test_sell_position_closes_with_buy() -> None:
    payload = close._close_payload(
        account_key="KEY",
        observation=_obs(direction="Sell"),
        external_reference="pg-close-test",
    )
    assert payload["BuySell"] == "Buy"


def test_precheck_requires_ok_and_no_disclaimers() -> None:
    assert close._precheck_is_clear({"PreCheckResult": "Ok"}) is True
    assert close._precheck_is_clear({"PreCheckResult": "Ok", "PreTradeDisclaimers": ["x"]}) is False
    assert close._precheck_is_clear({"PreCheckResult": "Error"}) is False


def test_trigger_basis_rejects_position_changes() -> None:
    state = {
        "uic": 42,
        "asset_type": "Stock",
        "direction": "Buy",
        "amount": 2.0,
        "average_open_price": 100.0,
    }
    assert close._same_trigger_basis(state, _obs()) is True
    assert close._same_trigger_basis(state, _obs(amount=3.0)) is False


def test_code_gate_defaults_closed(monkeypatch) -> None:
    monkeypatch.delenv(close.CODE_GATE_ENV, raising=False)
    assert close.code_gate_enabled_v1() is False
    monkeypatch.setenv(close.CODE_GATE_ENV, "true")
    assert close.code_gate_enabled_v1() is True


def test_disarmed_cycle_never_resolves_saxo_client(monkeypatch) -> None:
    monkeypatch.setattr(close, "ensure_live_close_schema_v1", lambda: None)
    monkeypatch.setattr(close, "load_live_close_config_v1", lambda: close.LiveCloseConfigV1(armed=False))
    monkeypatch.setattr(close, "code_gate_enabled_v1", lambda: True)

    def forbidden():
        raise AssertionError("Saxo client must not be touched while disarmed")

    monkeypatch.setattr(close, "_require_live_client", forbidden)
    summary = close.run_live_close_cycle_v1()
    assert summary.armed is False
    assert summary.submitted == 0


def test_source_has_live_and_idempotency_guards() -> None:
    source = open("autotrader_live_close_v1.py", encoding="utf-8").read()
    assert "LIVE_BASE_URL" in source
    assert "PRICEGAUGER_AUTOTRADER_LIVE_CLOSE_CODE_ENABLED" in source
    assert "pg_v2_autotrader_live_close_attempts" in source
    assert "STATUS_UNCERTAIN" in source
    assert '"ManualOrder": False' in source
    assert '"IsForceOpen": False' in source
