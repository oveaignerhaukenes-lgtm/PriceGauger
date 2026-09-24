from dataclasses import replace
from pathlib import Path

from autotrader_risk_control_v2 import PositionObservationV2
from tradingdesk_automanager_simple_v1 import _same_position_basis_v1


def test_takeover_requires_same_exact_saxo_position_basis():
    basis = PositionObservationV2(
        account_id="account", uic=4912, asset_type="CfdOnIndex",
        net_position_id="position-1", direction="Buy", amount=0.1,
        average_open_price=100.0, current_price=101.0, pnl_pct=1.0,
        price_delay_minutes=0, can_be_closed=True, calculation_reliability="Reliable",
    )
    assert _same_position_basis_v1(basis, basis)
    for change in (
        {"account_id": "other"}, {"uic": 4913}, {"asset_type": "FxSpot"},
        {"net_position_id": "position-2"}, {"direction": "Sell"},
        {"amount": 0.2}, {"average_open_price": 101.0},
    ):
        assert not _same_position_basis_v1(basis, replace(basis, **change))


def test_existing_live_enrollment_never_adopts_on_page_render():
    source = Path("tradingdesk_automanager_simple_v1.py").read_text(encoding="utf-8")
    assert "if st.button(\"Bekreft og overta Saxo-posisjon\"" in source
    assert "_same_position_basis_v1(observation, fresh)" in source
    assert source.count("adopt_user_confirmed_position_v2(enrollment, observation)") == 0
    assert "disabled=needs_takeover and not engine_on" in source
