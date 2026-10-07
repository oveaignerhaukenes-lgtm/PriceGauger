from saxo_provider import SaxoError
from autotrader_v3_live_runtime_v1 import (
    _definitive_saxo_rejection_v3,
    _margin_capacity_rejection_v3,
    _recorded_definitive_saxo_rejection_v3,
    _recorded_margin_capacity_rejection_v3,
)


def test_saxo_http_400_is_definitive_rejection():
    exc=SaxoError("WouldExceedMargin",status="REQUEST_FAILED",status_code=400)
    assert _definitive_saxo_rejection_v3(exc) is True


def test_timeout_and_rate_limit_remain_uncertain():
    assert _definitive_saxo_rejection_v3(
        SaxoError("timeout",status="TIMEOUT")
    ) is False
    assert _definitive_saxo_rejection_v3(
        SaxoError("rate limited",status="REQUEST_FAILED",status_code=429)
    ) is False
    assert _definitive_saxo_rejection_v3(
        SaxoError("request timeout",status="REQUEST_FAILED",status_code=408)
    ) is False


def test_server_error_remains_uncertain():
    assert _definitive_saxo_rejection_v3(
        SaxoError("server",status="REQUEST_FAILED",status_code=500)
    ) is False


def test_recorded_http_400_unknown_can_be_repaired_but_ambiguous_failures_cannot():
    assert _recorded_definitive_saxo_rejection_v3(
        "SaxoError: REQUEST_FAILED · HTTP 400: WouldExceedMargin"
    ) is True
    assert _recorded_definitive_saxo_rejection_v3(
        "SaxoError: REQUEST_FAILED · HTTP 429: rate limited"
    ) is False
    assert _recorded_definitive_saxo_rejection_v3(
        "SaxoError: CONNECTION_FAILED"
    ) is False


def test_margin_capacity_rejection_is_distinguished_from_other_400s():
    margin=SaxoError("REQUEST_FAILED · HTTP 400: {'ErrorInfo': {'ErrorCode': 'WouldExceedMargin'}}",status="REQUEST_FAILED",status_code=400)
    other=SaxoError("REQUEST_FAILED · HTTP 400: OtherError",status="REQUEST_FAILED",status_code=400)
    assert _margin_capacity_rejection_v3(margin) is True
    assert _margin_capacity_rejection_v3(other) is False
    assert _recorded_margin_capacity_rejection_v3("SaxoError: REQUEST_FAILED · HTTP 400: WouldExceedMargin") is True
    assert _recorded_margin_capacity_rejection_v3("SaxoError: REQUEST_FAILED · HTTP 400: OtherError") is False
