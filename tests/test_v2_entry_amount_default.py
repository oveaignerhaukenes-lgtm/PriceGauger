from __future__ import annotations

import autotrader_live_open_v2 as module


def test_unconfigured_amount_returns_none(monkeypatch):
    monkeypatch.delenv(module.V2_ENTRY_AMOUNT_ENV, raising=False)
    assert module._configured_entry_amount_v2() is None
