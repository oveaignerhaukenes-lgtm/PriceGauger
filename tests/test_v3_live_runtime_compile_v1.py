from pathlib import Path


def test_v3_live_runtime_compiles():
    source=Path('autotrader_v3_live_runtime_v1.py').read_text()
    compile(source,'autotrader_v3_live_runtime_v1.py','exec')
