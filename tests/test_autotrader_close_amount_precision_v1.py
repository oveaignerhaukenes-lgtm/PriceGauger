from types import SimpleNamespace

from autotrader_live_close_v1 import _close_payload


def test_close_payload_removes_binary_float_noise_from_amount() -> None:
    observation = SimpleNamespace(
        direction="Sell",
        amount=0.009999999999999953,
        asset_type="CfdOnIndex",
        uic=4912,
    )
    payload = _close_payload(account_key="account-key", observation=observation, external_reference="test")
    assert payload["Amount"] == 0.01
