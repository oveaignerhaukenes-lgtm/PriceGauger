from __future__ import annotations

import pytest

import autotrader_live_open_v2 as module


def test_fractional_entry_amount_configuration(monkeypatch):
    monkeypatch.setenv(module.V2_ENTRY_AMOUNT_ENV, "0.01")
    assert module._configured_entry_amount_v2() == pytest.approx(0.01)
