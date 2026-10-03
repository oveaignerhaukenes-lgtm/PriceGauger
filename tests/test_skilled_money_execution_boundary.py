from pathlib import Path


def test_skilled_money_page_has_no_execution_imports() -> None:
    source = Path("pages/10_Skilled_Money.py").read_text(encoding="utf-8").lower()
    forbidden = (
        "autotrader_live",
        "saxo_order",
        "order_execution",
        "execution_bridge",
        "reconciliation",
    )
    assert not any(name in source for name in forbidden)
