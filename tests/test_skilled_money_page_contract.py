from pathlib import Path


def test_skilled_money_page_marks_demo_and_revision_semantics() -> None:
    source = Path("pages/10_Skilled_Money.py").read_text(encoding="utf-8")
    assert "RETROSPEKTIV · DEMO" in source
    assert "Observed → Inferred → Later confirmed / weakened / refuted" in source
    assert "Revisjoner appendes" in source
