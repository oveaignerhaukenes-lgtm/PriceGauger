from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd
import yfinance as yf


@dataclass(frozen=True, slots=True)
class NumeraireAsset:
    label: str
    ticker: str
    category: str


GOLD_TICKER = "GC=F"

DEFAULT_ASSETS: tuple[NumeraireAsset, ...] = (
    NumeraireAsset("US dollar", "USD_GOLD", "Valuta"),
    NumeraireAsset("S&P 500", "^GSPC", "Aksjer"),
    NumeraireAsset("Nasdaq 100", "^NDX", "Aksjer"),
    NumeraireAsset("Silver", "SI=F", "Metaller"),
    NumeraireAsset("Brent oil", "BZ=F", "Energi"),
    NumeraireAsset("Bitcoin", "BTC-USD", "Krypto"),
    NumeraireAsset("US 10Y yield", "^TNX", "Renter"),
    NumeraireAsset("US 30Y yield", "^TYX", "Renter"),
)

PERIOD_OPTIONS: dict[str, str] = {
    "1 måned": "1mo",
    "3 måneder": "3mo",
    "6 måneder": "6mo",
    "1 år": "1y",
    "2 år": "2y",
    "5 år": "5y",
    "10 år": "10y",
    "Maks": "max",
}


def _clean_close(frame: pd.DataFrame | pd.Series, *, name: str) -> pd.Series:
    if isinstance(frame, pd.Series):
        series = frame.copy()
    elif "Close" in frame.columns:
        series = frame["Close"].copy()
    else:
        raise ValueError(f"{name}: mangler Close-serie")
    series = pd.to_numeric(series, errors="coerce").dropna()
    if series.empty:
        raise ValueError(f"{name}: ingen prisdata")
    index = pd.to_datetime(series.index, utc=True).tz_convert(None).normalize()
    series.index = index
    return series[~series.index.duplicated(keep="last")].sort_index().rename(name)


def fetch_close(ticker: str, *, period: str) -> pd.Series:
    history = yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=False)
    return _clean_close(history, name=ticker)


def align_to_gold(asset: pd.Series, gold: pd.Series) -> pd.DataFrame:
    """Align an asset to gold trading dates without manufacturing long gaps."""
    gold = _clean_close(gold, name="gold")
    asset = _clean_close(asset, name="asset")
    union = gold.index.union(asset.index).sort_values()
    gold_aligned = gold.reindex(union).ffill(limit=4)
    asset_aligned = asset.reindex(union).ffill(limit=4)
    joined = pd.concat([asset_aligned, gold_aligned], axis=1).dropna()
    joined.columns = ["asset", "gold"]
    return joined


def normalized_gold_ratio(asset: pd.Series, gold: pd.Series) -> pd.Series:
    """Asset/gold ratio indexed to 100 at the first common observation."""
    joined = align_to_gold(asset, gold)
    ratio = joined["asset"] / joined["gold"]
    ratio = ratio.replace([float("inf"), float("-inf")], pd.NA).dropna()
    if ratio.empty or float(ratio.iloc[0]) == 0.0:
        raise ValueError("Kan ikke normalisere tom eller null asset/gold-ratio")
    return (ratio / float(ratio.iloc[0]) * 100.0).rename("gold_index")


def normalized_usd_price(asset: pd.Series) -> pd.Series:
    asset = _clean_close(asset, name="asset")
    first = float(asset.iloc[0])
    if first == 0.0:
        raise ValueError("Kan ikke normalisere nullpris")
    return (asset / first * 100.0).rename("usd_index")


def dollar_in_gold_index(gold: pd.Series) -> pd.Series:
    """USD purchasing power measured in gold, indexed to 100 at the start."""
    gold = _clean_close(gold, name="gold")
    inverse = 1.0 / gold
    return (inverse / float(inverse.iloc[0]) * 100.0).rename("gold_index")


def build_numeraire_frame(
    prices: dict[str, pd.Series],
    *,
    gold: pd.Series,
    include_dollar: bool = True,
) -> pd.DataFrame:
    columns: list[pd.Series] = []
    if include_dollar:
        columns.append(dollar_in_gold_index(gold).rename("US dollar"))
    for label, asset in prices.items():
        columns.append(normalized_gold_ratio(asset, gold).rename(label))
    if not columns:
        return pd.DataFrame()
    return pd.concat(columns, axis=1).sort_index()


def latest_comparison(asset: pd.Series, gold: pd.Series) -> dict[str, float]:
    joined = align_to_gold(asset, gold)
    asset_usd = normalized_usd_price(joined["asset"])
    asset_gold = normalized_gold_ratio(joined["asset"], joined["gold"])
    return {
        "usd_change_pct": float(asset_usd.iloc[-1] - 100.0),
        "gold_change_pct": float(asset_gold.iloc[-1] - 100.0),
        "relative_gold_gap_pct": float(asset_gold.iloc[-1] - asset_usd.iloc[-1]),
    }


def asset_map(assets: Iterable[NumeraireAsset] = DEFAULT_ASSETS) -> dict[str, NumeraireAsset]:
    return {item.label: item for item in assets}
