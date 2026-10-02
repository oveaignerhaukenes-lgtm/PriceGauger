from pathlib import Path


def test_live_inventory_ownership_contract_is_documented_and_runtime_aligned():
    doc=Path('docs/AEN_V3_LIVE_INVENTORY_OWNERSHIP_2026-10-02.md').read_text()
    runtime=Path('autotrader_v3_live_runtime_v1.py').read_text()
    assert 'Saxo exact inventory is the source of truth' in doc
    assert 'Management authority covers the whole observed position' in doc
    assert 'Expansion authority remains separate' in doc
    assert 'LIVE account+instrument inventory adopted' in runtime
    assert "if mutation.action in {'REDUCE','CLOSE'}" in runtime
    assert "if mutation.action in {'OPEN','ADD'}" in runtime
    assert 'broker.precheck(order)' in runtime
