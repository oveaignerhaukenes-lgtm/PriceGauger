import pandas as pd

from market_data import MarketProvider, MarketRequest, fetch_market_data


class StubProvider(MarketProvider):
    def __init__(self, name: str, *, frame=None, error: Exception | None = None, supported: bool = True, reason: str | None = None):
        self.name = name
        self._frame = frame if frame is not None else pd.DataFrame()
        self._error = error
        self._supported = supported
        self._reason = reason

    def supports(self, request: MarketRequest) -> bool:
        return self._supported

    def unsupported_reason(self, request: MarketRequest) -> str | None:
        return self._reason

    def fetch(self, request: MarketRequest) -> pd.DataFrame:
        if self._error is not None:
            raise self._error
        return self._frame


def request() -> MarketRequest:
    return MarketRequest("Silver", "5min", 20, {"yahoo": "SI=F"})


def valid_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": [pd.Timestamp("2026-07-24T10:00:00Z")],
            "close": [57.8],
        }
    )


def test_successful_fallback_retains_primary_failure_reason():
    result = fetch_market_data(
        request(),
        [
            StubProvider("Saxo OpenAPI", error=RuntimeError("AUTH_FAILED · HTTP 401: token expired")),
            StubProvider("Yahoo Finance", frame=valid_frame()),
        ],
    )

    assert result.provider_name == "Yahoo Finance"
    assert result.used_fallback
    assert result.attempted_providers == ("Saxo OpenAPI", "Yahoo Finance")
    assert result.fallback_reasons == ("Saxo OpenAPI: AUTH_FAILED · HTTP 401: token expired",)


def test_unsupported_primary_provider_is_visible_in_fallback_reason():
    result = fetch_market_data(
        request(),
        [
            StubProvider(
                "Saxo OpenAPI",
                supported=False,
                reason="TOKEN_MISSING: Saxo access token mangler",
            ),
            StubProvider("Yahoo Finance", frame=valid_frame()),
        ],
    )

    assert result.provider_name == "Yahoo Finance"
    assert result.fallback_reasons == ("Saxo OpenAPI: TOKEN_MISSING: Saxo access token mangler",)


def test_empty_primary_response_is_visible():
    result = fetch_market_data(
        request(),
        [
            StubProvider("Saxo OpenAPI", frame=pd.DataFrame()),
            StubProvider("Yahoo Finance", frame=valid_frame()),
        ],
    )

    assert result.provider_name == "Yahoo Finance"
    assert result.fallback_reasons == ("Saxo OpenAPI: tom respons",)
