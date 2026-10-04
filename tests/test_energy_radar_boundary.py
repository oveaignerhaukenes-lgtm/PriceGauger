from pathlib import Path

from navigation_config import PAGE_GROUPS


def test_energy_radar_is_analysis_page():
    pages = PAGE_GROUPS["Analyse"]
    assert any(page["page"] == "pages/11_Energy_Radar.py" for page in pages)


def test_energy_radar_has_no_execution_dependencies():
    root = Path(__file__).resolve().parents[1]
    text = (root / "energy_radar_v1.py").read_text(encoding="utf-8") + (root / "pages" / "11_Energy_Radar.py").read_text(encoding="utf-8")
    forbidden = ("trade/v2/orders", "autotrader_live", "execution_bridge", "reconciliation", "place_order")
    for token in forbidden:
        assert token not in text
