from pathlib import Path


def test_mtf_short_live_contract_documents_execution_and_switch_invariants() -> None:
    text = Path("docs/MTF_SHORT_LIVE_V1.md").read_text(encoding="utf-8")
    assert "never calls Saxo order POST" in text
    assert "BOOTSTRAP_NO_REPLAY" in text
    assert "exact Saxo FLAT and no working order" in text
    assert "atomically in FK-safe order" in text
    assert "first OPEN may inherit source FLAT provenance" in text
    assert "SHORT Product Admission" in text
    assert "LIVE OPEN must then be armed explicitly" in text
