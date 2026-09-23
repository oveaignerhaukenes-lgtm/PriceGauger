from pathlib import Path

def test_v3_live_ui_does_not_claim_execution_is_disconnected():
    text=Path("pages/6_AutoTrader_POC.py").read_text(encoding="utf-8")
    assert "execution er fortsatt ikke koblet" not in text
    assert "LIVE AKTIV" in text
    assert "worker execution er koblet" in text
