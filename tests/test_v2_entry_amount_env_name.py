from __future__ import annotations

import autotrader_live_open_v2 as module


def test_entry_amount_configuration_key_is_stable():
    assert module.V2_ENTRY_AMOUNT_ENV == "PRICEGAUGER_V2_ENTRY_AMOUNT"
