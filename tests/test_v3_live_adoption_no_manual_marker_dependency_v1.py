from pathlib import Path


def test_live_runtime_no_longer_depends_on_manual_marker_provenance_for_adoption():
    source=Path('autotrader_v3_live_runtime_v1.py').read_text()
    assert 'manual_saxo_trade_markers_v1' not in source
    assert 'manual_fill_explains_inventory_change_v1' not in source
    assert 'inventory-adopted' in source
