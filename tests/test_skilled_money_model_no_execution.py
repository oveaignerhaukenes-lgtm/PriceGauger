from pathlib import Path


def test_snapshot_model_is_runtime_independent() -> None:
    source = Path("skilled_money_snapshot_v1.py").read_text(encoding="utf-8").lower()
    for forbidden in ("saxo", "autotrader", "order", "execution", "reconcile"):
        assert forbidden not in source
