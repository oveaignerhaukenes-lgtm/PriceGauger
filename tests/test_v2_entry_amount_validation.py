from __future__ import annotations

import pytest

import autotrader_live_open_v2 as module


def test_entry_amount_must_be_positive(monkeypatch):
    monkeypatch.setenv(module.V2_ENTRY_AMOUNT_ENV, "0")
    with pytest.raises(Exception, match="must be positive"):
        module._configured_entry_amount_v2()


def test_entry_amount_must_be_numeric(monkeypatch):
    monkeypatch.setenv(module.V2_ENTRY_AMOUNT_ENV, "invalid")
    with pytest.raises(Exception, match="must be numeric"):
        module._configured_entry_amount_v2()
