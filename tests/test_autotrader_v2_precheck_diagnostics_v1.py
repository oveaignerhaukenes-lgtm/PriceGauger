from types import SimpleNamespace

from autotrader_v2_precheck_diagnostics_v1 import (
    classify_precheck_block_v1,
    classify_precheck_exception_v1,
)
from saxo_provider import SaxoError


def _item(**overrides):
    values = dict(
        precheck_result="Ok",
        disclaimers_present=False,
        notional_account=3140.0,
        initial_margin_account=628.0,
        available_margin_after_account=9000.0,
        margin_decision=SimpleNamespace(allowed=True, reasons=(), effective_leverage=5.0),
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_saxo_rejection_is_not_hidden_as_combined_margin_error():
    block = classify_precheck_block_v1(_item(precheck_result="InsufficientCash"))
    assert block.category == "SAXO_PRECHECK"
    assert block.code == "InsufficientCash"


def test_margin_envelope_reason_and_metrics_are_visible():
    item = _item(margin_decision=SimpleNamespace(
        allowed=False,
        reasons=("EFFECTIVE_LEVERAGE_LIMIT",),
        effective_leverage=6.28,
    ))
    block = classify_precheck_block_v1(item)
    assert block.category == "MARGIN_ENVELOPE"
    assert block.code == "EFFECTIVE_LEVERAGE_LIMIT"
    assert "notional=3140.00" in block.detail
    assert "effective_leverage=6.28" in block.detail


def test_disclaimer_and_notional_cap_are_distinct_blockers():
    disclaimer = classify_precheck_block_v1(_item(disclaimers_present=True))
    assert disclaimer.code == "DISCLAIMERS"
    cap = classify_precheck_block_v1(_item(), max_notional_account=2500.0)
    assert cap.category == "SIZING"
    assert cap.code == "NOTIONAL_CAP"
    assert "cap=2500.00" in cap.detail


def test_clear_candidate_has_no_blocker():
    assert classify_precheck_block_v1(_item(), max_notional_account=4000.0) is None


def test_saxo_exception_preserves_safe_status():
    block = classify_precheck_exception_v1(SaxoError("not enough margin", status="ORDER_REJECTED"))
    assert block.category == "SAXO"
    assert block.code == "ORDER_REJECTED"
    assert "not enough margin" in block.detail
