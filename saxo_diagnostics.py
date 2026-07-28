from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True, slots=True)
class InfoPriceDiagnostic:
    status: str
    price_status: str
    delay_minutes: float | None
    bid: float | None
    ask: float | None
    mid: float | None
    has_price: bool
    has_access: bool
    explanation: str

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ChartDiagnostic:
    status: str
    bars: int
    first_timestamp: str | None
    last_timestamp: str | None
    last_close: float | None
    age_minutes: float | None
    explanation: str

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def diagnose_info_price(payload: dict[str, Any]) -> InfoPriceDiagnostic:
    quote = payload.get("Quote", {}) if isinstance(payload.get("Quote"), dict) else {}
    price_info = payload.get("PriceInfo", {}) if isinstance(payload.get("PriceInfo"), dict) else {}

    bid = _number(quote.get("Bid"))
    ask = _number(quote.get("Ask"))
    delay = _number(quote.get("DelayedByMinutes"))
    price_status = str(
        price_info.get("PriceStatus")
        or quote.get("PriceTypeBid")
        or quote.get("PriceTypeAsk")
        or "Unknown"
    )
    normalized_price_status = price_status.replace("_", "").replace(" ", "").lower()
    no_access = normalized_price_status in {"noaccess", "accessdenied", "notentitled"}

    if bid is not None and ask is not None:
        mid = (bid + ask) / 2.0
    else:
        mid = bid if bid is not None else ask
    has_price = mid is not None

    if no_access:
        status = "NO_ACCESS"
        explanation = "Saxo godkjente API-kallet, men kontoen har ikke prisrettighet for instrumentet i dette miljøet."
    elif delay is not None and delay > 0 and has_price:
        status = f"DELAYED_{int(delay)}MIN" if delay.is_integer() else f"DELAYED_{delay:g}MIN"
        explanation = f"Pris er tilgjengelig, men Saxo oppgir {delay:g} minutters forsinkelse."
    elif delay == 0 and has_price:
        status = "REALTIME"
        explanation = "Pris er tilgjengelig og Saxo oppgir ingen forsinkelse."
    elif has_price:
        status = "PRICE_AVAILABLE_DELAY_UNKNOWN"
        explanation = "Pris er tilgjengelig, men Saxo oppgir ikke forsinkelsen."
    else:
        status = "PRICE_UNAVAILABLE"
        explanation = "API-kallet lyktes, men responsen inneholdt ingen brukbar bid- eller ask-pris."

    return InfoPriceDiagnostic(
        status=status,
        price_status=price_status,
        delay_minutes=delay,
        bid=bid,
        ask=ask,
        mid=mid,
        has_price=has_price,
        has_access=not no_access,
        explanation=explanation,
    )


def diagnose_chart(frame: pd.DataFrame, *, now: pd.Timestamp | None = None) -> ChartDiagnostic:
    if frame.empty:
        return ChartDiagnostic(
            status="NO_BARS",
            bars=0,
            first_timestamp=None,
            last_timestamp=None,
            last_close=None,
            age_minutes=None,
            explanation="Chart-endepunktet svarte uten prisbarer.",
        )

    timestamps = pd.to_datetime(frame.get("timestamp"), utc=True, errors="coerce")
    closes = pd.to_numeric(frame.get("close"), errors="coerce")
    valid = pd.DataFrame({"timestamp": timestamps, "close": closes}).dropna()
    if valid.empty:
        return ChartDiagnostic(
            status="INVALID_BARS",
            bars=len(frame),
            first_timestamp=None,
            last_timestamp=None,
            last_close=None,
            age_minutes=None,
            explanation="Chart-endepunktet returnerte rader, men ingen gyldige tidspunkt/priser.",
        )

    current = now or pd.Timestamp.now(tz="UTC")
    if current.tzinfo is None:
        current = current.tz_localize("UTC")
    first = valid["timestamp"].iloc[0]
    last = valid["timestamp"].iloc[-1]
    age_minutes = max((current - last).total_seconds() / 60.0, 0.0)
    status = "CHART_AVAILABLE"
    explanation = f"{len(valid)} gyldige prisbarer mottatt; siste bar er {age_minutes:.1f} minutter gammel."

    return ChartDiagnostic(
        status=status,
        bars=len(valid),
        first_timestamp=first.isoformat(),
        last_timestamp=last.isoformat(),
        last_close=float(valid["close"].iloc[-1]),
        age_minutes=round(age_minutes, 3),
        explanation=explanation,
    )
