from __future__ import annotations

from pathlib import Path

from autotrader_entry_policy_v2 import PilotMarginConfigV2


def test_live_open_reloads_current_pilot_equity_before_sizing() -> None:
    source = Path("autotrader_live_open_legacy_v2.py").read_text(encoding="utf-8")
    assert "equity = load_pilot_equity_v2(pilot_key=enrollment.pilot_key)" in source
    assert "budget = float(equity.entry_budget)" in source
    assert "controlled_capital=budget" in source
    assert "find_largest_legal_entry_v2(" in source


def test_margin_envelope_tracks_current_compounded_pilot_capital() -> None:
    config = PilotMarginConfigV2(
        pilot_key="pilot-test",
        enabled=True,
        max_effective_leverage=6.0,
        minimum_free_capital=0.0,
    )
    envelope = config.envelope(currency="NOK", controlled_capital=750.0)

    assert envelope.capital_control_limit == 750.0
    assert envelope.max_initial_margin == 750.0
    assert envelope.max_notional_exposure == 4500.0
    assert envelope.max_effective_leverage == 6.0
