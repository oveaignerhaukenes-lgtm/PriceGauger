from datetime import datetime, timedelta, timezone

from market_data_freshness import classify_market_data_freshness
from realtime_market_data import RealtimeBar1m, StreamStatus


NOW = datetime(2026, 8, 10, 0, 30, tzinfo=timezone.utc)


def _bar(minutes_ago: float) -> RealtimeBar1m:
    stamp = NOW - timedelta(minutes=minutes_ago)
    return RealtimeBar1m(
        market="Gold",
        bar_time=stamp.isoformat(),
        open=1.0,
        high=1.0,
        low=1.0,
        close=1.0,
        sample_count=1,
        provider="Saxo OpenAPI",
        uic=1,
        asset_type="ContractFutures",
        symbol="GC",
    )


def _status(*, state: str = "CONNECTED", quote_seconds_ago: float = 30) -> StreamStatus:
    return StreamStatus(
        market="Gold",
        updated_at=NOW.isoformat(),
        state=state,
        last_quote_at=(NOW - timedelta(seconds=quote_seconds_ago)).isoformat(),
    )


def test_recent_bar_and_quote_are_fresh():
    result = classify_market_data_freshness(bar=_bar(1), status=_status(), now=NOW)
    assert result.state == "FRESH"
    assert "flyter" in result.label


def test_recent_quotes_with_stale_bar_warn_about_bar_pipeline():
    result = classify_market_data_freshness(bar=_bar(8), status=_status(quote_seconds_ago=20), now=NOW)
    assert result.state == "BAR_PIPELINE_WARNING"
    assert "1m-bars henger" in result.label


def test_old_quote_and_bar_do_not_claim_failure_when_market_may_be_closed():
    result = classify_market_data_freshness(
        bar=_bar(120),
        status=_status(quote_seconds_ago=7200),
        now=NOW,
    )
    assert result.state == "QUIET_OR_STALE"
    assert "stille/stengt" in result.detail


def test_disconnected_stream_is_explicit_warning():
    result = classify_market_data_freshness(
        bar=_bar(1),
        status=_status(state="ERROR"),
        now=NOW,
    )
    assert result.state == "STREAM_WARNING"
    assert "ERROR" in result.label
