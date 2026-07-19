from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

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


class MarketProvider(ABC):
    name: str

    @abstractmethod
    def supports(self, request: MarketRequest) -> bool:
        raise NotImplementedError

    @abstractmethod
    def fetch(self, request: MarketRequest) -> pd.DataFrame:
        raise NotImplementedError


class TwelveDataProvider(MarketProvider):
    name = "Twelve Data"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key.strip()

    def supports(self, request: MarketRequest) -> bool:
        return bool(self._api_key and request.symbols.get("twelve"))

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


def fetch_market_data(
    request: MarketRequest,
    providers: list[MarketProvider],
) -> MarketResult:
    errors: list[str] = []
    for provider in providers:
        if not provider.supports(request):
            continue
        try:
            frame = provider.fetch(request)
        except Exception as exc:
            errors.append(f"{provider.name}: {exc}")
            continue
        if not frame.empty:
            return MarketResult(frame=frame, provider_name=provider.name)
    detail = "; ".join(errors) if errors else "Ingen konfigurert leverandør støtter dette markedet."
    raise RuntimeError(detail)
