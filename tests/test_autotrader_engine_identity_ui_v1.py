from pathlib import Path

def test_autotrader_engine_identity_is_explicit():
    text=Path("pages/6_AutoTrader_POC.py").read_text(encoding="utf-8")
    assert 'ENGINE V3 · Target Inventory' in text
    assert 'ENGINE V2 · AutoManage' in text
    assert 'ENGINE V3 · {item.market_name} · LIVE' in text
    assert 'ENGINE V3 · {item.market_name} · SIM' in text
