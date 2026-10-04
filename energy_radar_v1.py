from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from saxo_provider import SaxoClient, SaxoInstrument


ENERGY_SEARCH_TERMS: tuple[str, ...] = ("UKOIL", "Brent", "Brent Crude", "ICE Brent")
PREFERRED_ASSET_TYPES: tuple[str, ...] = ("CfdOnFutures", "CfdOnIndex", "ContractFutures")


@dataclass(frozen=True, slots=True)
class EnergyRadarInstrumentV1:
    uic: int
    asset_type: str
    symbol: str
    description: str
    delay_minutes: int | None
    bid: float | None
    ask: float | None
    mid: float | None
    tradable: bool
    source_term: str

    @property
    def realtime(self) -> bool:
        return self.delay_minutes == 0


@dataclass(frozen=True, slots=True)
class EnergyRadarSnapshotV1:
    observed_at: datetime
    instruments: tuple[EnergyRadarInstrumentV1, ...]

    @property
    def preferred(self) -> EnergyRadarInstrumentV1 | None:
        if not self.instruments:
            return None
        return sorted(
            self.instruments,
            key=lambda item: (
                0 if item.symbol.upper().startswith("UKOIL") else 1,
                0 if item.realtime else 1,
                PREFERRED_ASSET_TYPES.index(item.asset_type) if item.asset_type in PREFERRED_ASSET_TYPES else 99,
                item.delay_minutes if item.delay_minutes is not None else 10_000,
            ),
        )[0]


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _delay(payload: dict[str, Any]) -> int | None:
    candidates = (
        payload.get("DelayedByMinutes"),
        (payload.get("PriceInfo") or {}).get("DelayedByMinutes") if isinstance(payload.get("PriceInfo"), dict) else None,
        (payload.get("Quote") or {}).get("DelayedByMinutes") if isinstance(payload.get("Quote"), dict) else None,
    )
    for value in candidates:
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _quote(payload: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
    quote = payload.get("Quote") if isinstance(payload.get("Quote"), dict) else {}
    price_info = payload.get("PriceInfo") if isinstance(payload.get("PriceInfo"), dict) else {}
    bid = _number(quote.get("Bid") if quote else price_info.get("Bid"))
    ask = _number(quote.get("Ask") if quote else price_info.get("Ask"))
    mid = _number(quote.get("Mid") if quote else price_info.get("Mid"))
    if mid is None and bid is not None and ask is not None:
        mid = (bid + ask) / 2.0
    return bid, ask, mid


def scan_brent_market_v1(client: SaxoClient) -> EnergyRadarSnapshotV1:
    """Discover Brent/UKOIL products and inspect their current read-only price entitlement.

    No order endpoint is called. A product is preferred only after Saxo reports its delay;
    UKOIL gets identity preference, but a delayed UKOIL will not silently be described as realtime.
    """
    found: dict[tuple[int, str], tuple[SaxoInstrument, str]] = {}
    for term in ENERGY_SEARCH_TERMS:
        for instrument in client.search_instruments(term):
            haystack = f"{instrument.symbol} {instrument.description}".upper()
            if not any(token in haystack for token in ("UKOIL", "BRENT")):
                continue
            found.setdefault((instrument.uic, instrument.asset_type), (instrument, term))

    rows: list[EnergyRadarInstrumentV1] = []
    for instrument, term in found.values():
        try:
            payload = client.info_price(instrument)
            bid, ask, mid = _quote(payload)
            delay = _delay(payload)
            rows.append(EnergyRadarInstrumentV1(instrument.uic, instrument.asset_type, instrument.symbol, instrument.description, delay, bid, ask, mid, True, term))
        except Exception:
            rows.append(EnergyRadarInstrumentV1(instrument.uic, instrument.asset_type, instrument.symbol, instrument.description, None, None, None, None, False, term))

    return EnergyRadarSnapshotV1(datetime.now(timezone.utc), tuple(rows))


def rows_v1(snapshot: EnergyRadarSnapshotV1) -> list[dict[str, Any]]:
    preferred = snapshot.preferred
    return [
        {
            "preferred": preferred is not None and (row.uic, row.asset_type) == (preferred.uic, preferred.asset_type),
            "symbol": row.symbol,
            "description": row.description,
            "asset_type": row.asset_type,
            "uic": row.uic,
            "delay_min": row.delay_minutes,
            "realtime": row.realtime,
            "bid": row.bid,
            "ask": row.ask,
            "mid": row.mid,
            "readable": row.tradable,
        }
        for row in snapshot.instruments
    ]
