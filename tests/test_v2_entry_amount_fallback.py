from __future__ import annotations

import autotrader_live_open_v2 as module


def test_no_configuration_preserves_existing_sizing_policy(monkeypatch):
    monkeypatch.delenv(module.V2_ENTRY_AMOUNT_ENV, raising=False)
    sentinel = object()
    monkeypatch.setattr(module, "_ORIGINAL_FIND_ENTRY", lambda *a, **k: sentinel)
    result = module._find_configured_entry_v2(
        object(),
        account_key="acct",
        account_currency="NOK",
        instrument=object(),
        direction="LONG",
        envelope=object(),
        controlled_capital=500.0,
        external_reference_prefix="test",
    )
    assert result is sentinel
