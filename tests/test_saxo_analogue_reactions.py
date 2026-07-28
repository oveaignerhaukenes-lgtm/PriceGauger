from __future__ import annotations

import pandas as pd

from gdelt_ingestion import GdeltCandidateRecord
from saxo_analogue_reactions import measure_brent_reactions, measure_candidate_reaction
from saxo_provider import SaxoInstrument


def candidate(published_at: str | None = "2026-07-24T12:00:00Z") -> GdeltCandidateRecord:
    return GdeltCandidateRecord(
        search_id="search-1",
        event_id="event-1",
        provider="GDELT BigQuery",
        query="test",
        title="Historical event",
        summary="Historical event",
        published_at=published_at,
        event_date="2026-07-24",
        country="IR",
        domain="example.com",
        url="https://example.com/event",
        retrieved_at="2026-07-28T12:00:00Z",
        raw={},
    )


class FakeClient:
    def __init__(self):
        self.future_space_calls = []
        self.chart_calls = []

    def future_space(self, continuous_uic):
        self.future_space_calls.append(continuous_uic)
        return [
            SaxoInstrument(
                asset="Brent",
                uic=43074091,
                asset_type="ContractFutures",
                symbol="LCOU6",
                expiry="2026-07-31",
            )
        ]

    def chart(self, instrument, **kwargs):
        self.chart_calls.append((instrument, kwargs))
        timestamps = pd.date_range("2026-07-24T12:00:00Z", periods=289, freq="5min")
        closes = [100.0 + index * 0.01 for index in range(len(timestamps))]
        return pd.DataFrame(
            {
                "timestamp": timestamps,
                "open": closes,
                "high": [value + 0.2 for value in closes],
                "low": [value - 0.2 for value in closes],
                "close": closes,
            }
        )


def test_measure_candidate_reaction_calculates_short_horizon_returns():
    client = FakeClient()
    contracts = client.future_space(4055)

    result = measure_candidate_reaction(candidate(), client=client, contracts=contracts)

    assert result.status == "OK"
    assert result.contract_symbol == "LCOU6"
    assert result.contract_uic == 43074091
    assert result.price_at_event == 100.0
    assert round(result.return_15m_pct or 0, 4) == 0.03
    assert round(result.return_1h_pct or 0, 4) == 0.12
    assert round(result.return_4h_pct or 0, 4) == 0.48
    assert round(result.return_24h_pct or 0, 4) == 2.88
    assert result.mfe_4h_pct is not None
    assert result.mae_4h_pct is not None
    assert client.chart_calls[0][1]["time"] == pd.Timestamp("2026-07-24T12:00:00Z")
    assert client.chart_calls[0][1]["mode"] == "From"


def test_measure_candidate_reaction_requires_exact_timestamp():
    client = FakeClient()

    result = measure_candidate_reaction(candidate(None), client=client, contracts=client.future_space(4055))

    assert result.status == "TIMESTAMP_MISSING"
    assert client.chart_calls == []


def test_measure_brent_reactions_loads_future_space_once():
    client = FakeClient()

    results = measure_brent_reactions([candidate(), candidate()], client=client)

    assert len(results) == 2
    assert client.future_space_calls == [4055]
