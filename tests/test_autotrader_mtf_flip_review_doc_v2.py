from __future__ import annotations

from pathlib import Path


def test_mtf_flip_review_notes_preserve_fail_closed_reversal_contract() -> None:
    text = Path("docs/MTF_FLIP_REVIEW_NOTES_V1.md").read_text(encoding="utf-8")
    assert "no Saxo POST authority" in text
    assert "Opposite exposure maps to CLOSE; only observed FLAT maps to OPEN" in text
    assert "5m/10m rejection events flatten only" in text
    assert "BOOTSTRAP_NO_REPLAY" in text
    assert "Product Admission" in text
    assert "fail-closed" in text
