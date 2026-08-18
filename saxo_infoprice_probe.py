from __future__ import annotations

from dataclasses import dataclass
import logging
import time
from typing import Any, Callable, Mapping

from saxo_provider import SaxoClient, SaxoInstrument


LOGGER = logging.getLogger("pricegauger.saxo_infoprice_probe")
DEFAULT_PROBE_SECONDS = 300
FIELD_GROUPS = "InstrumentPriceDetails,PriceInfo,PriceInfoDetails,Quote"


@dataclass(frozen=True, slots=True)
class InfoPriceDiagnostic:
    market: str
    uic: int
    asset_type: str
    last_updated: str | None
    is_market_open: bool | None
    delayed_by_minutes: float | None
    error_code: str | None
    price_type_bid: str | None
    price_type_ask: str | None
    bid: float | None
    ask: float | None
    mid: float | None
    last_traded: float | None


def _number(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _diagnostic_from_row(*, market: str, instrument: SaxoInstrument, row: Mapping[str, Any]) -> InfoPriceDiagnostic:
    quote = row.get("Quote") if isinstance(row.get("Quote"), Mapping) else {}
    details = row.get("InstrumentPriceDetails") if isinstance(row.get("InstrumentPriceDetails"), Mapping) else {}
    price_details = row.get("PriceInfoDetails") if isinstance(row.get("PriceInfoDetails"), Mapping) else {}
    is_open = details.get("IsMarketOpen")
    return InfoPriceDiagnostic(
        market=market,
        uic=instrument.uic,
        asset_type=instrument.asset_type,
        last_updated=None if row.get("LastUpdated") is None else str(row.get("LastUpdated")),
        is_market_open=is_open if isinstance(is_open, bool) else None,
        delayed_by_minutes=_number(quote.get("DelayedByMinutes")),
        error_code=None if quote.get("ErrorCode") is None else str(quote.get("ErrorCode")),
        price_type_bid=None if quote.get("PriceTypeBid") is None else str(quote.get("PriceTypeBid")),
        price_type_ask=None if quote.get("PriceTypeAsk") is None else str(quote.get("PriceTypeAsk")),
        bid=_number(quote.get("Bid")),
        ask=_number(quote.get("Ask")),
        mid=_number(quote.get("Mid")),
        last_traded=_number(price_details.get("LastTraded")),
    )


def fetch_infoprice_diagnostics(
    *,
    client: SaxoClient,
    instruments: Mapping[str, SaxoInstrument],
) -> tuple[InfoPriceDiagnostic, ...]:
    """Read Saxo InfoPrices without changing collection or trading state.

    Saxo's list endpoint accepts one AssetType plus a comma-separated UIC list.
    We therefore group the active runtime instruments by AssetType and map each
    returned row back to the canonical PriceGauger market name.
    """
    grouped: dict[str, list[tuple[str, SaxoInstrument]]] = {}
    for market, instrument in instruments.items():
        grouped.setdefault(instrument.asset_type, []).append((market, instrument))

    diagnostics: list[InfoPriceDiagnostic] = []
    for asset_type, members in grouped.items():
        payload = client._get(  # noqa: SLF001 - diagnostic uses the provider's authenticated request contract
            "trade/v1/infoprices/list",
            params={
                "AssetType": asset_type,
                "Uics": ",".join(str(instrument.uic) for _, instrument in members),
                "FieldGroups": FIELD_GROUPS,
            },
        )
        rows = payload.get("Data", []) if isinstance(payload, dict) else []
        by_uic = {
            int(row["Uic"]): row
            for row in rows
            if isinstance(row, Mapping) and row.get("Uic") is not None
        }
        for market, instrument in members:
            row = by_uic.get(int(instrument.uic))
            if row is None:
                diagnostics.append(
                    InfoPriceDiagnostic(
                        market=market,
                        uic=instrument.uic,
                        asset_type=instrument.asset_type,
                        last_updated=None,
                        is_market_open=None,
                        delayed_by_minutes=None,
                        error_code="MISSING_FROM_RESPONSE",
                        price_type_bid=None,
                        price_type_ask=None,
                        bid=None,
                        ask=None,
                        mid=None,
                        last_traded=None,
                    )
                )
                continue
            diagnostics.append(_diagnostic_from_row(market=market, instrument=instrument, row=row))
    return tuple(diagnostics)


def log_infoprice_diagnostics(*, client: SaxoClient, instruments: Mapping[str, SaxoInstrument]) -> None:
    for item in fetch_infoprice_diagnostics(client=client, instruments=instruments):
        LOGGER.info(
            "Saxo InfoPrice diagnostic market=%s uic=%s asset_type=%s market_open=%s delayed_minutes=%s error_code=%s price_type_bid=%s price_type_ask=%s bid=%s ask=%s mid=%s last_traded=%s last_updated=%s",
            item.market,
            item.uic,
            item.asset_type,
            item.is_market_open,
            item.delayed_by_minutes,
            item.error_code,
            item.price_type_bid,
            item.price_type_ask,
            item.bid,
            item.ask,
            item.mid,
            item.last_traded,
            item.last_updated,
        )


def run_infoprice_probe_forever(
    *,
    client: SaxoClient,
    instruments: Mapping[str, SaxoInstrument],
    stop_requested: Callable[[], bool],
    interval_seconds: int = DEFAULT_PROBE_SECONDS,
) -> None:
    interval = max(60, int(interval_seconds))
    while not stop_requested():
        try:
            log_infoprice_diagnostics(client=client, instruments=instruments)
        except Exception as exc:
            LOGGER.warning("Saxo InfoPrice diagnostic failed: %s", exc, exc_info=True)
        for _ in range(interval):
            if stop_requested():
                return
            time.sleep(1)
