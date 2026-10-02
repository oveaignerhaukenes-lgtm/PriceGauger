from __future__ import annotations

import pytest

import autotrader_live_open_v2 as module


def test_negative_entry_amount_is_invalid(monkeypatch):
    monkeypatch.setenv(module.V2_ENTRY_AMOUNT_ENV, "-0.01")
    with pytest.raises(Exception, match="must be positive"):
        module._configured_entry_amount_v2()
