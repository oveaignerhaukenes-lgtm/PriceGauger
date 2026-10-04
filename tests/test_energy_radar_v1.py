from energy_radar_v1 import EnergyRadarInstrumentV1, EnergyRadarSnapshotV1, scan_brent_market_v1
from saxo_provider import SaxoInstrument
from datetime import datetime, timezone


class FakeClient:
    def search_instruments(self, term):
        if term == "UKOIL":
            return [SaxoInstrument("Brent", 10, "CfdOnFutures", "UKOIL", "Brent Crude CFD")]
        if term == "Brent":
            return [SaxoInstrument("Brent", 20, "ContractFutures", "LCOV6", "Brent Crude Oct 2026")]
        return []

    def info_price(self, instrument):
        if instrument.uic == 10:
            return {"PriceInfo": {"DelayedByMinutes": 0}, "Quote": {"Bid": 92.0, "Ask": 92.1}}
        return {"PriceInfo": {"DelayedByMinutes": 15}, "Quote": {"Bid": 91.9, "Ask": 92.0}}


def test_scan_prefers_realtime_ukoil_and_deduplicates_search_hits():
    snapshot = scan_brent_market_v1(FakeClient())
    assert len(snapshot.instruments) == 2
    assert snapshot.preferred is not None
    assert snapshot.preferred.symbol == "UKOIL"
    assert snapshot.preferred.realtime is True
    assert snapshot.preferred.mid == 92.05


def test_unknown_delay_is_not_realtime():
    row = EnergyRadarInstrumentV1(1, "CfdOnFutures", "UKOIL", "Brent", None, 1.0, 1.1, 1.05, True, "UKOIL")
    assert row.realtime is False


def test_delayed_feed_is_not_reported_realtime():
    snapshot = EnergyRadarSnapshotV1(datetime.now(timezone.utc), (EnergyRadarInstrumentV1(1, "ContractFutures", "LCO", "Brent", 15, 1.0, 1.1, 1.05, True, "Brent"),))
    assert snapshot.preferred is not None
    assert snapshot.preferred.realtime is False
    assert snapshot.preferred.delay_minutes == 15
