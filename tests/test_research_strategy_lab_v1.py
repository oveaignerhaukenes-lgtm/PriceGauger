from pathlib import Path
from research_strategy_store_v1 import STRATEGY_KEY_GOLD_FED

ROOT = Path(__file__).resolve().parents[1]

def test_gold_fed_research_strategy_is_navigation_visible() -> None:
    nav = (ROOT / "navigation_config.py").read_text(encoding="utf-8")
    assert "pages/0_Strategy_Lab.py" in nav
    assert '"Strategy Lab"' in nav

def test_gold_fed_page_keeps_research_separate_from_execution() -> None:
    source = (ROOT / "pages/0_Strategy_Lab.py").read_text(encoding="utf-8")
    assert "STRATEGY_KEY_GOLD_FED" in source
    assert "ingen execution authority" in source
    assert "Hypotesetidslinje" in source
    assert "Revider hypotesen" in source
