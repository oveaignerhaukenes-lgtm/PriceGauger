from __future__ import annotations

import autotrader_live_open_v2 as module


def test_entry_amount_is_not_fixed_to_point_zero_one(monkeypatch):
    monkeypatch.setenv(module.V2_ENTRY_AMOUNT_ENV, "1.25")
    assert module._configured_entry_amount_v2() == 1.25
