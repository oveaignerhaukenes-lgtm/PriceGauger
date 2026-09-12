from pathlib import Path

from navigation_config import PAGE_GROUPS


def test_autodesk_is_mounted_beside_tradingdesk() -> None:
    pages = PAGE_GROUPS[""]
    paths = [item["page"] for item in pages]
    assert "pages/0_TradingDesk.py" in paths
    assert "pages/0_Autodesk.py" in paths
    assert paths.index("pages/0_Autodesk.py") == paths.index("pages/0_TradingDesk.py") + 1


def test_autodesk_starts_analysis_only_and_reuses_shared_workspace() -> None:
    source = Path("pages/0_Autodesk.py").read_text(encoding="utf-8")
    assert "RealtimeMarketDataStore" in source
    assert "load_trading_desk_contexts_v2" in source
    assert "ingen execution-authority" in source
    assert "NO-TRADE" in source
    assert "Opportunity" in source
    forbidden = ("place_order", "saxo_order", "execute_order", "broker POST")
    assert not any(token in source for token in forbidden)
