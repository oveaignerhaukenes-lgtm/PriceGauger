from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_binary_macd_close_can_rebase_after_exact_basis_drifts() -> None:
    source = (ROOT / "autotrader_strategy_live_close_v2.py").read_text(encoding="utf-8")

    assert "def _binary_macd_managed_identity_is_authorized" in source
    assert "net_position_id = ?" in source
    assert "uic = ? AND asset_type = ? AND managed = TRUE" in source
    assert "current.direction.strip().lower()" in source
    assert '_record_dict(row).get("direction")' in source

    strict = source.index("exact_managed = is_position_managed_v1(current)")
    binary = source.index("binary_managed_identity = _binary_macd_managed_identity_is_authorized", strict)
    block = source.index("POSITION_NOT_EXACTLY_MANAGED", binary)
    rebase = source.index("binary MACD close rebased", block)

    assert strict < binary < block < rebase
    assert "if not exact_managed and not binary_managed_identity" in source
    assert "if binary_managed_identity:" in source
