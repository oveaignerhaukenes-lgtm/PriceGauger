import pandas as pd

from market_data import MarketProvider, MarketRequest, fetch_market_data


class StubProvider(MarketProvider):
    def __init__(
        self,
        name: str,
        *,
        frame=None,
        error: Exception | None = None,
        supported: bool = True,
        reason: str | None = None,
        metadata: dict | None = None,
    ):
        self.name = name
        self._frame = frame if frame is not None else pd.DataFrame()
        self._error = error
        self._supported = supported
        self._reason = reason
        self._metadata = metadata or {}

    def supports(self, request: MarketRequest) -> bool:
        return self._supported

    def unsupported_reason(self, request: MarketRequest) -> str | None:
        return self._reason

    def fetch(self, request: MarketRequest) -> pd.DataFrame:
        if self._error is not None:
            raise self._error
        return self._frame

    def result_metadata(self, request: MarketRequest, frame: pd.DataFrame) -> dict[str, object]:
        return self._metadata


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


def test_successful_result_records_market_timestamp_and_dynamic_observed_delay():
    result = fetch_market_data(request(), [StubProvider("Saxo OpenAPI", frame=valid_frame())])

    assert result.market_timestamp == pd.Timestamp("2026-07-24T10:00:00Z")
    assert result.received_at is not None
    assert result.observed_delay_minutes is not None
    assert result.observed_delay_minutes >= 0
    assert result.declared_delay_minutes is None
    assert result.feed_type == "CHART"
    assert result.feed_quality == "SAXO_CHART_AVAILABLE"
    assert "observert forsinkelse" in result.source_label()


def test_provider_can_attach_declared_delay_and_environment_without_overwriting_observed_delay():
    result = fetch_market_data(
        request(),
        [
            StubProvider(
                "Saxo OpenAPI",
                frame=valid_frame(),
                metadata={
                    "declared_delay_minutes": 15.0,
                    "feed_type": "CHART",
                    "feed_quality": "DELAYED_CHART",
                    "provider_environment": "SIM",
                },
            )
        ],
    )

    assert result.declared_delay_minutes == 15.0
    assert result.observed_delay_minutes is not None
    assert result.feed_quality == "DELAYED_CHART"
    assert result.provider_environment == "SIM"
