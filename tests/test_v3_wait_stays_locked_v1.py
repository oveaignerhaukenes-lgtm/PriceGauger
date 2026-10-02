from pathlib import Path


def test_wait_state_is_not_adopted_or_retried():
    source=Path('autotrader_v3_live_runtime_v1.py').read_text()
    wait=source.index("elif reconciliation.state=='WAIT':")
    conflict=source.index("LIVE authority is ownership",wait)
    block=source[wait:conflict]
    assert "pending=waiting; no retry sent" in block
    assert 'mark_order_v3' not in block
    assert 'place_order' not in block
