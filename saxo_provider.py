from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import requests

from market_data import MarketProvider, MarketRequest


SIM_BASE_URL = "https://gateway.saxobank.com/sim/openapi"
LIVE_BASE_URL = "https://gateway.saxobank.com/openapi"


class SaxoError(RuntimeError):
    """Safe Saxo failure suitable for provider fallback diagnostics."""

    def __init__(self, message: str, *, status: str = "REQUEST_FAILED", status_code: int | None = None) -> None:
        self.status = status
        self.status_code = status_code
        prefix = status
        if status_code is not None:
            prefix += f" · HTTP {status_code}"
        super().__init__(f"{prefix}: {message}")


@dataclass(frozen=True, slots=True)
class SaxoInstrument:
    asset: str
    uic: int
    asset_type: str
    symbol: str = ""
    description: str = ""
    expiry: str | None = None
    price_multiplier: float = 1.0

    @classmethod
    def from_mapping(cls, asset: str, value: dict[str, Any]) -> "SaxoInstrument":
        multiplier = float(value.get("price_multiplier", 1.0))
        if multiplier <= 0:
            raise ValueError(f"price_multiplier for {asset} må være større enn 0")
        return cls(
            asset=asset,
            uic=int(value["uic"]),
            asset_type=str(value["asset_type"]),
            symbol=str(value.get("symbol", "")),
            description=str(value.get("description", "")),
            expiry=str(value["expiry"]) if value.get("expiry") else None,
            price_multiplier=multiplier,
        )


class SaxoClient:
    def __init__(
        self,
        access_token: str,
        *,
        base_url: str = SIM_BASE_URL,
        timeout: float = 20.0,
        session: requests.Session | None = None,
    ) -> None:
        token = access_token.strip()
        if not token:
            raise ValueError("Saxo access token mangler")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "User-Agent": "PriceGauger/1.0-alpha",
            }
        )

    def _get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            response = self.session.get(
                f"{self.base_url}/{path.lstrip('/')}",
                params=params,
                timeout=self.timeout,
            )
        except requests.Timeout as exc:
            raise SaxoError(f"tidsavbrudd etter {self.timeout:g} sekunder", status="TIMEOUT") from exc
        except requests.ConnectionError as exc:
            raise SaxoError("kunne ikke opprette forbindelse", status="CONNECTION_FAILED") from exc
        except requests.RequestException as exc:
            raise SaxoError(type(exc).__name__, status="REQUEST_FAILED") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise SaxoError("responsen var ikke gyldig JSON", status="INVALID_RESPONSE", status_code=response.status_code) from exc

        if not response.ok:
            message = "forespørselen ble avvist"
            if isinstance(payload, dict):
                error_info = payload.get("ErrorInfo") if isinstance(payload.get("ErrorInfo"), dict) else {}
                message = str(
                    error_info.get("Message")
                    or error_info.get("ErrorCode")
                    or payload.get("Message")
                    or payload.get("message")
                    or message
                )
            status = "AUTH_FAILED" if response.status_code in {401, 403} else "REQUEST_FAILED"
            raise SaxoError(message, status=status, status_code=response.status_code)
        if not isinstance(payload, dict):
            raise SaxoError("forventet JSON-objekt", status="INVALID_RESPONSE", status_code=response.status_code)
        return payload

    def search_instruments(
        self,
        keywords: str,
        *,
        asset_types: str = "ContractFutures,CfdOnFutures,CfdOnIndex,StockIndex",
    ) -> list[SaxoInstrument]:
        payload = self._get(
            "ref/v1/instruments",
            params={"Keywords": keywords, "AssetTypes": asset_types},
        )
        instruments: list[SaxoInstrument] = []
        raw = payload.get("Data", [])
        if not isinstance(raw, list):
            raise SaxoError("instrumentlisten hadde ugyldig format", status="INVALID_RESPONSE")
        for item in raw:
            if not isinstance(item, dict):
                continue
            identifier = item.get("Identifier")
            asset_type = item.get("AssetType")
            if identifier is None or not asset_type:
                continue
            instruments.append(
                SaxoInstrument(
                    asset=keywords,
                    uic=int(identifier),
                    asset_type=str(asset_type),
                    symbol=str(item.get("Symbol", "")),
                    description=str(item.get("Description", "")),
                    expiry=str(item.get("ExpiryDate")) if item.get("ExpiryDate") else None,
                )
            )
        return instruments

    def instrument_details(self, instrument: SaxoInstrument) -> dict[str, Any]:
        return self._get(
            f"ref/v1/instruments/details/{instrument.uic}/{instrument.asset_type}",
            params={"FieldGroups": "MarketData"},
        )

    def chart(
        self,
        instrument: SaxoInstrument,
        *,
        horizon_minutes: int = 1,
        count: int = 1200,
    ) -> pd.DataFrame:
        payload = self._get(
            "chart/v3/charts",
            params={
                "Uic": instrument.uic,
                "AssetType": instrument.asset_type,
                "Horizon": horizon_minutes,
                "Count": min(max(int(count), 1), 1200),
                "FieldGroups": "Data",
            },
        )
        rows = payload.get("Data", [])
        if rows is None:
            rows = []
        if not isinstance(rows, list):
            raise SaxoError("chart-data hadde ugyldig format", status="INVALID_RESPONSE")
        if not rows:
            return pd.DataFrame()
        frame = pd.DataFrame(rows)
        frame["timestamp"] = pd.to_datetime(frame.get("Time"), utc=True, errors="coerce")
        column_candidates = {
            "open": ("OpenBid", "OpenAsk", "Open"),
            "high": ("HighBid", "HighAsk", "High"),
            "low": ("LowBid", "LowAsk", "Low"),
            "close": ("CloseBid", "CloseAsk", "Close"),
            "volume": ("Volume",),
        }
        price_columns: list[str] = []
        for target, candidates in column_candidates.items():
            source = next((name for name in candidates if name in frame.columns), None)
            if source is not None:
                frame[target] = pd.to_numeric(frame[source], errors="coerce")
                if target != "volume":
                    price_columns.append(target)
        if "close" not in frame:
            raise SaxoError("chart-respons mangler close-pris", status="INVALID_RESPONSE")
        if instrument.price_multiplier != 1.0:
            frame[price_columns] = frame[price_columns] * instrument.price_multiplier
        wanted = [column for column in ("timestamp", "open", "high", "low", "close", "volume") if column in frame]
        return frame[wanted].dropna(subset=["timestamp", "close"]).sort_values("timestamp").reset_index(drop=True)


def _secret(name: str) -> str:
    environment = os.getenv(name, "").strip()
    if environment:
        return environment
    try:
        import streamlit as st

        try:
            value = st.secrets.get(name, "")
        except Exception:
            return ""
        return str(value).strip() if value else ""
    except ImportError:
        return ""


def configured_instruments() -> dict[str, SaxoInstrument]:
    raw = _secret("SAXO_INSTRUMENTS_JSON")
    if not raw:
        return {}
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("SAXO_INSTRUMENTS_JSON må være et JSON-objekt")
    return {asset: SaxoInstrument.from_mapping(asset, value) for asset, value in payload.items()}


def configured_client() -> SaxoClient | None:
    token = _secret("SAXO_ACCESS_TOKEN")
    if not token:
        return None
    environment = (_secret("SAXO_ENVIRONMENT") or "sim").lower()
    base_url = _secret("SAXO_BASE_URL") or (LIVE_BASE_URL if environment == "live" else SIM_BASE_URL)
    return SaxoClient(token, base_url=base_url)


class SaxoPriceProvider(MarketProvider):
    name = "Saxo OpenAPI"

    def __init__(
        self,
        client: SaxoClient | None = None,
        instruments: dict[str, SaxoInstrument] | None = None,
    ) -> None:
        self.client = client or configured_client()
        self.instruments = instruments if instruments is not None else configured_instruments()

    def supports(self, request: MarketRequest) -> bool:
        instrument = self.instruments.get(request.asset_name)
        return self.client is not None and instrument is not None and instrument_is_unexpired(instrument)

    def unsupported_reason(self, request: MarketRequest) -> str | None:
        if self.client is None:
            return "TOKEN_MISSING: Saxo access token mangler"
        instrument = self.instruments.get(request.asset_name)
        if instrument is None:
            return f"INSTRUMENT_MISSING: {request.asset_name} er ikke konfigurert"
        if not instrument_is_unexpired(instrument):
            return f"INSTRUMENT_EXPIRED: kontrakten for {request.asset_name} er utløpt"
        return None

    def fetch(self, request: MarketRequest) -> pd.DataFrame:
        if self.client is None:
            raise SaxoError("Saxo er ikke konfigurert", status="TOKEN_MISSING")
        instrument = self.instruments.get(request.asset_name)
        if instrument is None:
            raise SaxoError(f"{request.asset_name} er ikke konfigurert", status="INSTRUMENT_MISSING")
        if not instrument_is_unexpired(instrument):
            raise SaxoError(f"kontrakten for {request.asset_name} er utløpt", status="INSTRUMENT_EXPIRED")
        horizon = {"1min": 1, "5min": 5, "15min": 15, "30min": 30, "1h": 60}.get(request.interval)
        if horizon is None:
            raise ValueError(f"Ustøttet Saxo-intervall: {request.interval}")
        return self.client.chart(instrument, horizon_minutes=horizon, count=request.outputsize)


def instrument_candidates() -> dict[str, tuple[str, str]]:
    return {
        "Brent": ("Brent", "ContractFutures,CfdOnFutures"),
        "Gold": ("Gold", "ContractFutures,CfdOnFutures"),
        "Silver": ("Silver", "ContractFutures,CfdOnFutures"),
        "DXY": ("US Dollar Index", "ContractFutures,CfdOnFutures,CfdOnIndex,StockIndex"),
    }


def discover_instruments(client: SaxoClient) -> dict[str, list[SaxoInstrument]]:
    return {
        asset: client.search_instruments(keywords, asset_types=asset_types)
        for asset, (keywords, asset_types) in instrument_candidates().items()
    }


def instrument_is_unexpired(instrument: SaxoInstrument, now: datetime | None = None) -> bool:
    if not instrument.expiry:
        return True
    expiry = pd.Timestamp(instrument.expiry)
    if expiry.tzinfo is None:
        expiry = expiry.tz_localize("UTC")
    current = pd.Timestamp(now or datetime.now(timezone.utc))
    return expiry >= current
