from pathlib import Path


def test_three_trader_tv_has_no_execution_authority():
    root = Path(__file__).resolve().parents[1]
    source = (root / "tradingdesk_ui/charts/lightweight/three_trader_tv_v1.py").read_text(encoding="utf-8")
    forbidden = ("saxo", "broker", "persist_intent", "order_request", "POST /openapi")
    lowered = source.lower()
    for token in forbidden:
        assert token.lower() not in lowered
