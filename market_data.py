from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd
import requests
import yfinance as yf


@dataclass(slots=True)
class MarketRequest:
    asset_name: str
    interval: str
    outputsize: int
    symbols: dict[str, str]


@dataclass(slots=True)
class MarketResult:
    frame: pd.DataFrame
    provider_name: str
    attempted_providers: tuple[str, ...] = ()
    fallback_reasons: tuple[str, ...] = ()
    market_timestamp: pd.Timestamp | None = None
    received_at: pd.Timestamp | None = None
    observed_delay_minutes: float | None = None
    declared_delay_minutes: float | None = None
    feed_type: str = "CHART"
    feed_quality: str = "UNKNOWN"
    provider_environment: str = "UNKNOWN"

    @property
    def used_fallback(self) -> bool:
        return bool(self.fallback_reasons)

    def source_label(self) -> str:
        if self.observed_delay_minutes is None:
            return f"{self.provider_name} · forsinkelse ukjent"
        return f"{self.provider_name} · observert forsinkelse {self.observed_delay_minutes:.1f} min"


class MarketProvider(ABC):
    name: str

    @abstractmethod
    def supports(self, request: MarketRequest) -> bool:
        raise NotImplementedError

    @abstractmethod
    def fetch(self, request: MarketRequest) -> pd.DataFrame:
        raise NotImplementedError

    def unsupported_reason(self, request: MarketRequest) -> str | None:
        """Return a safe diagnostic when supports() is false."""
        return None

    def result_metadata(self, request: MarketRequest, frame: pd.DataFrame) -> dict[str, object]:
        """Optional non-price metadata attached to a successful provider result."""
        return {}


class TwelveDataProvider(MarketProvider):
    name = "Twelve Data"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key.strip()

    def supports(self, request: MarketRequest) -> bool:
        return bool(self._api_key and request.symbols.get("twelve"))

    def unsupported_reason(self, request: MarketRequest) -> str | None:
        if not self._api_key:
            return "API-nøkkel mangler"
        if not request.symbols.get("twelve"):
            return f"symbol mangler for {request.asset_name}"
        return None

    def fetch(self, request: MarketRequest) -> pd.DataFrame:
        response = requests.get(
            "https://api.twelvedata.com/time_series",
            params={
                "symbol": request.symbols["twelve"],
                "interval": request.interval,
                "outputsize": min(max(request.outputsize, 1), 5000),
                "timezone": "UTC",
                "order": "asc",
                "apikey": self._api_key,
            },
            timeout=30,
        )
        payload = response.json()
        if response.status_code >= 400 or payload.get("status") == "error":
            raise RuntimeError(payload.get("message", f"HTTP {response.status_code}"))
        values = payload.get("values", [])
        if not values:
            return pd.DataFrame()
        frame = pd.DataFrame(values)
        frame["timestamp"] = pd.to_datetime(frame["datetime"], utc=True, errors="coerce")
        for col in ("open", "high", "low", "close", "volume"):
            if col in frame:
                frame[col] = pd.to_numeric(frame[col], errors="coerce")
        return frame.dropna(subset=["timestamp", "close"]).sort_values("timestamp").reset_index(drop=True)


class YahooProvider(MarketProvider):
    name = "Yahoo Finance"

    def supports(self, request: MarketRequest) -> bool:
        return bool(request.symbols.get("yahoo"))

    def unsupported_reason(self, request: MarketRequest) -> str | None:
        if not request.symbols.get("yahoo"):
            return f"symbol mangler for {request.asset_name}"
        return None

    def fetch(self, request: MarketRequest) -> pd.DataFrame:
        yahoo_interval = {"5min": "5m", "15min": "15m", "30min": "30m", "1h": "1h"}[request.interval]
        yahoo_period = "60d" if request.interval in {"5min", "15min", "30min"} else "730d"
        frame = yf.download(
            request.symbols["yahoo"],
            period=yahoo_period,
            interval=yahoo_interval,
            auto_adjust=False,
            progress=False,
            threads=False,
        )
        if frame.empty:
            return frame
        if isinstance(frame.columns, pd.MultiIndex):
            frame.columns = frame.columns.get_level_values(0)
        frame = frame.reset_index()
        time_col = "Datetime" if "Datetime" in frame.columns else "Date"
        frame[time_col] = pd.to_datetime(frame[time_col], utc=True, errors="coerce")
        frame = frame.rename(
            columns={
                time_col: "timestamp",
                "Close": "close",
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Volume": "volume",
            }
        )
        frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
        return frame.dropna(subset=["timestamp", "close"]).sort_values("timestamp").reset_index(drop=True)


def _result_timing(frame: pd.DataFrame) -> tuple[pd.Timestamp | None, pd.Timestamp, float | None]:
    received_at = pd.Timestamp(datetime.now(timezone.utc))
    if "timestamp" not in frame or frame.empty:
        return None, received_at, None
    timestamps = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce").dropna()
    if timestamps.empty:
        return None, received_at, None
    market_timestamp = timestamps.max()
    observed_delay = max((received_at - market_timestamp).total_seconds() / 60.0, 0.0)
    return market_timestamp, received_at, observed_delay


def _default_feed_quality(provider_name: str, observed_delay_minutes: float | None) -> str:
    if observed_delay_minutes is None:
        return "DELAY_UNKNOWN"
    if provider_name.lower().startswith("saxo"):
        return "SAXO_CHART_AVAILABLE"
    return "CHART_AVAILABLE"


def fetch_market_data(
    request: MarketRequest,
    providers: list[MarketProvider],
) -> MarketResult:
    attempted: list[str] = []
    diagnostics: list[str] = []

    for provider in providers:
        attempted.append(provider.name)
        if not provider.supports(request):
            reason = provider.unsupported_reason(request)
            if reason:
                diagnostics.append(f"{provider.name}: {reason}")
            continue
        try:
            frame = provider.fetch(request)
        except Exception as exc:
            diagnostics.append(f"{provider.name}: {exc}")
            continue
        if frame.empty:
            diagnostics.append(f"{provider.name}: tom respons")
            continue

        market_timestamp, received_at, observed_delay = _result_timing(frame)
        metadata = provider.result_metadata(request, frame)
        return MarketResult(
            frame=frame,
            provider_name=provider.name,
            attempted_providers=tuple(attempted),
            fallback_reasons=tuple(diagnostics),
            market_timestamp=market_timestamp,
            received_at=received_at,
            observed_delay_minutes=observed_delay,
            declared_delay_minutes=metadata.get("declared_delay_minutes"),
            feed_type=str(metadata.get("feed_type") or "CHART"),
            feed_quality=str(metadata.get("feed_quality") or _default_feed_quality(provider.name, observed_delay)),
            provider_environment=str(metadata.get("provider_environment") or "UNKNOWN"),
        )

    detail = "; ".join(diagnostics) if diagnostics else "Ingen konfigurert leverandør støtter dette markedet."
    raise RuntimeError(detail)
