from pathlib import Path


def test_strategy_close_preserves_saxo_precheck_error_info_contract() -> None:
    source = Path("autotrader_strategy_live_close_v2.py").read_text(encoding="utf-8")

    assert "precheck_failure_diagnostics_v1(precheck)" in source
    assert "block_reason=diagnostic.block_reason" in source
    assert "strategy CLOSE precheck blocked" in source
    assert "error_code=%s" in source
    assert "error_message=%s" in source
    assert "response_keys=%s" in source
    assert 'payload.get("AccountKey")' not in source
    assert 'precheck=%s' not in source
