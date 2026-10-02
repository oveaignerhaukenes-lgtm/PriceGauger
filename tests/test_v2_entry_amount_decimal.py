from __future__ import annotations

import autotrader_live_open_v2 as module


def test_decimal_deployment_amount(monkeypatch):
    monkeypatch.setenv(module.V2_ENTRY_AMOUNT_ENV, "0.03")
    assert module._configured_entry_amount_v2() == 0.03
