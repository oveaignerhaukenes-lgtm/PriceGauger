from autotrader_precheck_diagnostics_v1 import precheck_failure_diagnostics_v1


def test_extracts_saxo_error_info_without_persisting_sensitive_fields() -> None:
    diagnostic = precheck_failure_diagnostics_v1({
        "PreCheckResult": "Error",
        "ErrorInfo": {
            "ErrorCode": "AmountBelowMinimumLotSize",
            "Message": "Order size is below the minimum exchange lot size.",
        },
        "ExternalReference": "do-not-persist",
        "PreTradeDisclaimers": {"DisclaimerTokens": ["secret-token"]},
    })

    assert diagnostic.result == "Error"
    assert diagnostic.error_code == "AmountBelowMinimumLotSize"
    assert diagnostic.error_message == "Order size is below the minimum exchange lot size."
    assert diagnostic.has_disclaimers is True
    assert diagnostic.block_reason == (
        "Error:AmountBelowMinimumLotSize:Order size is below the minimum exchange lot size.:DISCLAIMERS"
    )
    assert "do-not-persist" not in diagnostic.block_reason
    assert "secret-token" not in diagnostic.block_reason
    assert diagnostic.response_keys == ("ErrorInfo", "ExternalReference", "PreCheckResult", "PreTradeDisclaimers")


def test_missing_error_info_still_produces_actionable_shape() -> None:
    diagnostic = precheck_failure_diagnostics_v1({"PreCheckResult": "Error"})
    assert diagnostic.block_reason == "Error"
    assert diagnostic.error_code == ""
    assert diagnostic.error_message == ""
    assert diagnostic.has_disclaimers is False
