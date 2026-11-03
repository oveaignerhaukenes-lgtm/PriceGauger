"""Protect Saxo's manual/automatic order-origin classification.

No Saxo credentials or live order calls are used here.
"""
from pathlib import Path
import pytest
from saxo_trading import SaxoOrderRequest
from saxo_provider import SaxoInstrument


def _inst():
    return SaxoInstrument(asset="index", uic=4912, asset_type="CfdOnIndex",
                          symbol="US Tech 100")


def test_manual_default_preserves_existing_user_confirmed_orders():
    request = SaxoOrderRequest("key", _inst(), 0.01, "Buy")
    assert request.payload()["ManualOrder"] is True


def test_explicit_automated_origin_is_false_and_identity_unchanged():
    request = SaxoOrderRequest("key", _inst(), 0.02, "Sell",
                               external_reference="pgv3-example",
                               manual_order=False)
    payload = request.payload()
    assert payload["ManualOrder"] is False
    assert payload["AccountKey"] == "key"
    assert payload["AssetType"] == "CfdOnIndex"
    assert payload["Uic"] == 4912
    assert payload["Amount"] == 0.02
    assert payload["ExternalReference"] == "pgv3-example"


@pytest.mark.parametrize("invalid", [None, "false", 0, 1])
def test_manual_origin_rejects_ambiguous_values(invalid):
    request = SaxoOrderRequest("key", _inst(), 0.01, "Buy",
                               manual_order=invalid)
    with pytest.raises(ValueError, match="manual_order must be a boolean"):
        request.payload()


def test_v3_runtime_opt_in_only_no_change_to_broker_authority():
    source = Path("autotrader_v3_live_runtime_v1.py").read_text()
    assert "manual_order=False)  # Saxo automatic order-entry classification" in source
    assert "broker.precheck(order)" in source
    assert "broker.place_order(order,confirm_live=True)" in source
    assert "reserve_order_v3(" in source
