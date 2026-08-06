from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

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
        access_token: str | None = None,
        *,
        access_token_getter: Callable[..., str] | None = None,
        base_url: str = SIM_BASE_URL,
        timeout: float = 20.0,
        session: requests.Session | None = None,
    ) -> None:
        token = (access_token or "").strip()
        if not token and access_token_getter is None:
            raise ValueError("Saxo access token mangler")
        self._static_access_token = token
        self._access_token_getter = access_token_getter
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": "PriceGauger/1.0-alpha",
            }
        )
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"

    def _set_authorization(self, *, force_refresh: bool = False) -> None:
        if self._access_token_getter is not None:
            try:
                token = self._access_token_getter(force_refresh=force_refresh)
            except TypeError:
                token = self._access_token_getter()
            except Exception as exc:
                status = getattr(exc, "status", "AUTH_FAILED")
                raise SaxoError(str(exc), status=status) from exc
        else:
            token = self._static_access_token
        if not token:
            raise SaxoError("Saxo access token mangler", status="TOKEN_MISSING")
        self.session.headers["Authorization"] = f"Bearer {token}"

    def _get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}/{path.lstrip('/')}"
        for attempt in range(2):
            self._set_authorization(force_refresh=attempt == 1)
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
            except requests.Timeout as exc:
                raise SaxoError(f"tidsavbrudd etter {self.timeout:g} sekunder", status="TIMEOUT") from exc
            except requests.ConnectionError as exc:
                raise SaxoError("kunne ikke opprette forbindelse", status="CONNECTION_FAILED") from exc
            except requests.RequestException as exc:
                raise SaxoError(type(exc).__name__, status="REQUEST_FAILED") from exc

            if response.status_code == 401 and self._access_token_getter is not None and attempt == 0:
                continue
            break

        try:
            payload = response.json()
        except ValueError as exc:
            raise SaxoError(
                "responsen var ikke gyldig JSON",
                status="INVALID_RESPONSE",
                status_code=response.status_code,
            ) from exc

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

    def future_space(self, continuous_uic: int) -> list[SaxoInstrument]:
        payload = self._get(f"ref/v1/instruments/futuresspaces/{int(continuous_uic)}")
        rows = payload.get("Elements") or payload.get("Data") or []
        if not isinstance(rows, list):
            raise SaxoError("future-space hadde ugyldig format", status="INVALID_RESPONSE")

        instruments: list[SaxoInstrument] = []
        for item in rows:
            if not isinstance(item, dict):
                continue
            uic = item.get("Uic") or item.get("Identifier")
            asset_type = item.get("AssetType") or "ContractFutures"
            if uic is None:
                continue
            instruments.append(
                SaxoInstrument(
                    asset="",
                    uic=int(uic),
                    asset_type=str(asset_type),
                    symbol=str(item.get("Symbol") or ""),
                    description=str(item.get("Description") or ""),
                    expiry=str(item.get("ExpiryDate")) if item.get("ExpiryDate") else None,
                )
            )
        return instruments

    def info_price(self, instrument: SaxoInstrument) -> dict[str, Any]:
        return self._get(
            "trade/v1/infoprices",
            params={
                "Uic": instrument.uic,
                "AssetType": instrument.asset_type,
                "FieldGroups": "DisplayAndFormat,PriceInfo,Quote",
            },
        )

    def chart(
        self,
        instrument: SaxoInstrument,
        *,
        horizon_minutes: int = 1,
        count: int = 1200,
        time: datetime | pd.Timestamp | str | None = None,
        mode: str | None = None,
    ) -> pd.DataFrame:
        params: dict[str, Any] = {
            "Uic": instrument.uic,
            "AssetType": instrument.asset_type,
            "Horizon": horizon_minutes,
            "Count": min(max(int(count), 1), 1200),
            "FieldGroups": "Data",
        }
        if time is not None:
            timestamp = pd.Timestamp(time)
            if timestamp.tzinfo is None:
                timestamp = timestamp.tz_localize("UTC")
            else:
                timestamp = timestamp.tz_convert("UTC")
            params["Time"] = timestamp.isoformat().replace("+00:00", "Z")
            params["Mode"] = mode or "From"
        elif mode is not None:
            params["Mode"] = mode

        payload = self._get("chart/v3/charts", params=params)
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


def select_contract_for_timestamp(
    contracts: list[SaxoInstrument],
    timestamp: datetime | pd.Timestamp | str,
    *,
    minimum_days_to_expiry: int = 2,
) -> SaxoInstrument:
    target = pd.Timestamp(timestamp)
    if target.tzinfo is None:
        target = target.tz_localize("UTC")
    else:
        target = target.tz_convert("UTC")

    eligible: list[tuple[pd.Timestamp, SaxoInstrument]] = []
    for contract in contracts:
        if not contract.expiry:
            continue
        expiry = pd.Timestamp(contract.expiry)
        if expiry.tzinfo is None:
            expiry = expiry.tz_localize("UTC")
        else:
            expiry = expiry.tz_convert("UTC")
        if expiry >= target + pd.Timedelta(days=minimum_days_to_expiry):
            eligible.append((expiry, contract))

    if not eligible:
        raise SaxoError("ingen gyldig futureskontrakt for tidspunktet", status="INSTRUMENT_MISSING")
    eligible.sort(key=lambda item: item[0])
    return eligible[0][1]


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
    environment = (_secret("SAXO_ENVIRONMENT") or "sim").lower()
    base_url = _secret("SAXO_BASE_URL") or (LIVE_BASE_URL if environment == "live" else SIM_BASE_URL)

    try:
        from saxo_auth import configured_oauth_client

        oauth = configured_oauth_client(_secret)
    except (ImportError, ValueError):
        oauth = None
    if oauth is not None:
        try:
            oauth.status()
        except Exception:
            pass
        return SaxoClient(access_token_getter=oauth.access_token, base_url=base_url)

    token = _secret("SAXO_ACCESS_TOKEN")
    if not token:
        return None
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
            return "TOKEN_MISSING: Saxo OAuth eller access token mangler"
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
        # Saxo may expose a Treasury future rather than the cash yield itself.
        # The UI therefore labels the selected result as a possible inverse proxy.
        "US10Y": ("US 10 Year Treasury", "ContractFutures,CfdOnFutures,CfdOnIndex,StockIndex"),
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


def instrument_config_payload(
    instruments: dict[str, SaxoInstrument],
    *,
    price_multipliers: dict[str, float] | None = None,
) -> dict[str, dict[str, Any]]:
    """Build the non-secret JSON payload expected by SAXO_INSTRUMENTS_JSON."""
    multipliers = price_multipliers or {}
    payload: dict[str, dict[str, Any]] = {}
    for asset, instrument in instruments.items():
        multiplier = float(multipliers.get(asset, instrument.price_multiplier))
        if multiplier <= 0:
            raise ValueError(f"price_multiplier for {asset} må være større enn 0")
        payload[asset] = {
            "uic": instrument.uic,
            "asset_type": instrument.asset_type,
            "symbol": instrument.symbol,
            "description": instrument.description,
            "expiry": instrument.expiry,
            "price_multiplier": multiplier,
        }
    return payload


def latest_gold_silver_ratio(
    gold: pd.DataFrame,
    silver: pd.DataFrame,
    *,
    tolerance: str = "15min",
) -> dict[str, Any]:
    """Return the latest synchronized gold/silver observation and ratio."""
    required = {"timestamp", "close"}
    if not required.issubset(gold.columns) or not required.issubset(silver.columns):
        raise ValueError("Gull- og sølvseriene må inneholde timestamp og close")

    left = gold[["timestamp", "close"]].rename(columns={"close": "gold"}).copy()
    right = silver[["timestamp", "close"]].rename(columns={"close": "silver"}).copy()
    left["timestamp"] = pd.to_datetime(left["timestamp"], utc=True, errors="coerce")
    right["timestamp"] = pd.to_datetime(right["timestamp"], utc=True, errors="coerce")
    left["gold"] = pd.to_numeric(left["gold"], errors="coerce")
    right["silver"] = pd.to_numeric(right["silver"], errors="coerce")
    left = left.dropna().sort_values("timestamp")
    right = right.dropna().sort_values("timestamp")
    if left.empty or right.empty:
        raise ValueError("Gull- eller sølvserien mangler gyldige prisdata")

    synchronized = pd.merge_asof(
        left,
        right,
        on="timestamp",
        direction="nearest",
        tolerance=pd.Timedelta(tolerance),
    ).dropna(subset=["silver"])
    synchronized = synchronized[synchronized["silver"] > 0]
    if synchronized.empty:
        raise ValueError("Fant ingen samtidige gull- og sølvpriser")
    latest = synchronized.iloc[-1]
    return {
        "timestamp": latest["timestamp"],
        "gold": float(latest["gold"]),
        "silver": float(latest["silver"]),
        "ratio": float(latest["gold"] / latest["silver"]),
    }
