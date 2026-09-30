from autotrader_v3_order_reconciliation_v1 import V3ReconciliationPhaseError
from saxo_provider import SaxoError


def test_audit_http_diagnostic_is_bounded_and_redacts_message():
    error = SaxoError("sensitive provider payload", status="AUTH_FAILED", status_code=403)
    result = V3ReconciliationPhaseError("audit_fetch", error)
    assert str(result) == "audit_fetch: SaxoError: AUTH_FAILED_http_403"
    assert "sensitive" not in str(result)


def test_unrecognized_error_does_not_expose_message():
    result = V3ReconciliationPhaseError("audit_fetch", RuntimeError("secret"))
    assert str(result) == "audit_fetch: RuntimeError"
