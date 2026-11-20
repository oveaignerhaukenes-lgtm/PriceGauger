"""Authenticated Saxo source discovery is manual GET-only, not a strategy."""
from datetime import datetime, timedelta, timezone
import unittest

from tech100_treasury_source_probe_v1 import (
    TENOR_TERMS, TreasuryCandidate, probe_treasury_quote, search_treasury_candidates,
)

NOW = datetime(2026, 11, 20, 15, 0, tzinfo=timezone.utc)


class FakeSaxo:
    def __init__(self, quote=None):
        self.calls = []
        self.quote = quote or {}

    def _get(self, path, *, params):
        self.calls.append((path, dict(params)))
        if path == "ref/v1/instruments":
            return {"Data": [
                {"Identifier": 100 + len(self.calls), "AssetType": "ContractFutures",
                 "Symbol": "2YYX6", "Description": params["Keywords"] + " - Nov 2026"},
                {"Identifier": 999, "AssetType": "ContractFutures",
                 "Symbol": "MNQZ6", "Description": "Micro E-mini Nasdaq 100"},
                {"Identifier": "bad", "AssetType": "Bond"},
                {"Identifier": 7, "AssetType": "Stock"},
            ]}
        if path == "trade/v1/infoprices":
            return self.quote
        raise AssertionError("No other endpoint is authorized")


class TreasurySourceProbeContracts(unittest.TestCase):
    def test_search_uses_only_bounded_instrument_gets(self):
        client = FakeSaxo()
        found = search_treasury_candidates(client)
        self.assertEqual(set(found), set(TENOR_TERMS))
        self.assertTrue(all(len(found[tenor]) == 1 for tenor in TENOR_TERMS))
        self.assertEqual(len(client.calls), 3)
        self.assertEqual({path for path, _ in client.calls}, {"ref/v1/instruments"})
        self.assertTrue(all("Bond" in args["AssetTypes"] for _, args in client.calls))
        self.assertEqual(list(TENOR_TERMS.values()), [
            "Micro 2-Year Yield", "Micro 10-Year Yield", "Micro 30-Year Yield",
        ])
        self.assertTrue(all(found[tenor][0].asset_type == "ContractFutures" for tenor in TENOR_TERMS))

    def test_verified_yield_fields_do_not_mean_constant_maturity(self):
        candidate = TreasuryCandidate("US10Y", 22, "Bond", "TNOTE", "Treasury", None)
        client = FakeSaxo({
            "LastUpdated": NOW.isoformat(),
            "Quote": {"Bid": 99, "Ask": 101, "DelayedByMinutes": 0, "ErrorCode": "None"},
            "PriceInfoDetails": {"BidYield": 3.7, "AskYield": 3.6},
        })
        observed = probe_treasury_quote(client, candidate, at=NOW)
        self.assertEqual(observed.status, "YIELD_OBSERVED")
        self.assertEqual(observed.bid_yield_raw, 3.7)
        self.assertEqual(client.calls[0][0], "trade/v1/infoprices")
        self.assertIn("PriceInfoDetails", client.calls[0][1]["FieldGroups"])

    def test_future_or_cfd_price_is_explicit_proxy_only(self):
        candidate = TreasuryCandidate("US2Y", 33, "CfdOnFutures", "ZT", "2y future", None)
        client = FakeSaxo({
            "LastUpdated": NOW.isoformat(),
            "Quote": {"Bid": 105, "Ask": 106, "DelayedByMinutes": 0},
            "PriceInfoDetails": {},
        })
        self.assertEqual(probe_treasury_quote(client, candidate, at=NOW).status, "PRICE_PROXY_ONLY")

    def test_delayed_or_stale_quote_is_never_considered_ready(self):
        candidate = TreasuryCandidate("US30Y", 44, "Bond", "TBOND", "30y", None)
        delayed = FakeSaxo({
            "LastUpdated": NOW.isoformat(),
            "Quote": {"DelayedByMinutes": 15},
            "PriceInfoDetails": {"BidYield": 4.1},
        })
        self.assertEqual(probe_treasury_quote(delayed, candidate, at=NOW).status, "DELAYED")
        stale = FakeSaxo({
            "LastUpdated": (NOW - timedelta(minutes=3)).isoformat(),
            "Quote": {"DelayedByMinutes": 0},
            "PriceInfoDetails": {"BidYield": 4.1},
        })
        self.assertEqual(probe_treasury_quote(stale, candidate, at=NOW).status, "STALE")


if __name__ == "__main__":
    unittest.main()
