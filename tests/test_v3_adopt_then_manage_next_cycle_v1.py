from pathlib import Path


def test_adoption_reconciles_stale_request_and_defers_management_to_next_cycle():
    source=Path('autotrader_v3_live_runtime_v1.py').read_text()
    marker="pending=inventory-adopted; next cycle may manage actual"
    assert marker in source
    adoption=source.index(marker)
    next_cycle=source.index('continue',adoption)
    fresh_read=source.index('actual=_actual(e,broker)',next_cycle)
    assert adoption < next_cycle < fresh_read
