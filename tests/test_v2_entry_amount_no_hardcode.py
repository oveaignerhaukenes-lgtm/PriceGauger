from __future__ import annotations

import autotrader_live_open_v2 as module


def test_entry_amount_can_change_at_runtime(monkeypatch):
    monkeypatch.setenv(module.V2_ENTRY_AMOUNT_ENV, "0.02")
    first = module._configured_entry_amount_v2()
    monkeypatch.setenv(module.V2_ENTRY_AMOUNT_ENV, "0.20")
    second = module._configured_entry_amount_v2()
    assert first == 0.02
    assert second == 0.20
