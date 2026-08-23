from __future__ import annotations

from autotrader_managed_positions_v1 import managed_position_matches_v1
from autotrader_risk_dry_run_v2 import PositionObservationV2


def _obs(*, amount: float = 2.0, opening: float = 100.0, position_id: str = "NP1") -> PositionObservationV2:
    return PositionObservationV2(
        account_id="A1",
        net_position_id=position_id,
        uic=42,
        asset_type="Stock",
        direction="Buy",
        amount=amount,
        average_open_price=opening,
        current_price=101.0,
        pnl_pct=1.0,
        price_delay_minutes=0,
        can_be_closed=True,
        calculation_reliability="Ok",
        is_market_open=True,
        non_tradable_reason="None",
    )


def _record() -> dict[str, object]:
    return {
        "account_id": "A1",
        "net_position_id": "NP1",
        "uic": 42,
        "asset_type": "Stock",
        "direction": "Buy",
        "amount": 2.0,
        "average_open_price": 100.0,
        "managed": True,
    }


def test_exact_enrolled_position_is_managed() -> None:
    assert managed_position_matches_v1(_record(), _obs()) is True


def test_new_or_resized_position_does_not_inherit_auto_manage() -> None:
    assert managed_position_matches_v1(_record(), _obs(amount=3.0)) is False
    assert managed_position_matches_v1(_record(), _obs(opening=101.0)) is False
    assert managed_position_matches_v1(_record(), _obs(position_id="NP2")) is False


def test_disabled_enrollment_is_not_managed() -> None:
    record = _record()
    record["managed"] = False
    assert managed_position_matches_v1(record, _obs()) is False


def test_ui_exposes_explicit_auto_manage_button() -> None:
    source = open("autotrader_live_close_ui_v1.py", encoding="utf-8").read()
    assert 'button("Auto-manage"' in source
    assert 'button("Stopp auto-manage"' in source
    assert "Nye posisjoner tas aldri automatisk over" in source
