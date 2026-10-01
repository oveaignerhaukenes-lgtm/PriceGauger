from pathlib import Path


def test_reset_on_loss_pnl_failure_does_not_block_v3_base_strategy():
    source=Path("autotrader_v3_live_runtime_v1.py").read_text()
    anchor=source.index("v3 Reset on Loss skipped")
    window=source[anchor-350:anchor+350]
    assert "_record_runtime(e.pilot_key,'BLOCKED'" not in window
    assert "continue" not in window
    assert "modifiers.append(ResetOnLossModifierV3" in source[anchor:anchor+500]
