from __future__ import annotations

from pathlib import Path

from navigation_config import PAGE_GROUPS


def test_benchmark_page_is_exposed_under_results():
    pages = PAGE_GROUPS["Resultater"]
    benchmark = next(item for item in pages if item["page"] == "pages/7_Benchmark.py")
    assert benchmark["title"] == "Benchmark"


def test_benchmark_page_states_preview_is_read_only_and_learning_off():
    source = Path("pages/7_Benchmark.py").read_text(encoding="utf-8")
    assert "lagres ikke, trener ingenting" in source
    assert "Læring: AV" in source
    assert "0 % = TECH_ONLY" in source
    assert "100 % = dagens faste TECH+CONTEXT-kandidat" in source
