from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Callable

from market_data import MarketRequest, MarketResult
from state_contracts import ComponentStatus, MarketStateSnapshot
from technical_analysis import TechnicalSnapshot, build_multi_timeframe_snapshot
from technical_regime import TechnicalRegime, build_technical_regime

ENGINE_VERSION = "technical-state-runtime-v1"
TIMEFRAMES = {"5m": "5min", "30m": "30min", "1h": "1h"}
ASSET_SYMBOLS = {
    "Brent": {"yahoo": "BZ=F"},
    "Silver": {"twelve": "XAG/USD", "yahoo": "SI=F"},
    "Gold": {"twelve": "XAU/USD", "yahoo": "GC=F"},
    "DXY": {"yahoo": "DX-Y.NYB"},
}


def _stable_id(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return "market-state:" + sha256(canonical.encode("utf-8")).hexdigest()[:24]


def _bias_score(regime: TechnicalRegime) -> float:
    return {
        "BULLISH": 1.0,
        "SLIGHTLY BULLISH": 0.45,
        "NEUTRAL": 0.0,
        "SLIGHTLY BEARISH": -0.45,
        "BEARISH": -1.0,
    }.get(regime.bias, 0.0)


def _quality_scale(regime: TechnicalRegime) -> float:
    return {"HIGH": 1.0, "MEDIUM": 0.75, "LOW": 0.45, "INSUFFICIENT": 0.0}.get(
        regime.signal_quality, 0.0
    )


def market_state_from_technical(
    market: str,
    snapshots: dict[str, TechnicalSnapshot],
    regime: TechnicalRegime,
    *,
    providers: dict[str, str],
    now: datetime | None = None,
) -> MarketStateSnapshot:
    if not snapshots:
        raise ValueError(f"Ingen tekniske snapshots for {market}")
    latest = max(snapshots.values(), key=lambda item: item.timestamp)
    observed = datetime.fromisoformat(latest.timestamp.replace("Z", "+00:00"))
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    age_seconds = max(0, int((current.astimezone(timezone.utc) - observed.astimezone(timezone.utc)).total_seconds()))
    freshness = "FRESH" if age_seconds <= 2 * 3600 else "STALE"
    direction = _bias_score(regime) * _quality_scale(regime)
    atr_values = [item.atr_14_pct for item in snapshots.values() if item.atr_14_pct is not None]
    payload = {
        "market": market,
        "observed_at": observed.isoformat(),
        "price": latest.price,
        "direction": direction,
        "regime": regime.regime,
    }
    return MarketStateSnapshot(
        snapshot_id=_stable_id(payload),
        market=market,
        as_of=observed.isoformat(),
        price=latest.price,
        direction_score=direction,
        volatility_score=min(1.0, max(atr_values, default=0.0) / 2.0),
        momentum_score=direction,
        price_confirmation=direction,
        regime=f"{regime.bias} · {regime.signal_quality} · {regime.regime}",
        component=ComponentStatus(
            observed_at=observed.isoformat(),
            age_seconds=age_seconds,
            freshness=freshness,
            provider=" / ".join(sorted(set(providers.values()))),
            instrument=market,
            engine_version=ENGINE_VERSION,
        ),
    )


def build_technical_market_states(
    markets: list[str] | tuple[str, ...],
    *,
    fetcher: Callable[[MarketRequest], MarketResult],
    outputsize: int = 300,
    now: datetime | None = None,
) -> tuple[dict[str, MarketStateSnapshot], dict[str, str]]:
    states: dict[str, MarketStateSnapshot] = {}
    errors: dict[str, str] = {}
    for market in markets:
        symbols = ASSET_SYMBOLS.get(market)
        if symbols is None:
            errors[market] = "Markedet mangler instrumentmapping."
            continue
        frames: dict = {}
        providers: dict[str, str] = {}
        try:
            for timeframe, interval in TIMEFRAMES.items():
                result = fetcher(MarketRequest(market, interval, outputsize, symbols))
                frames[timeframe] = result.frame
                providers[timeframe] = result.provider_name
            snapshots = build_multi_timeframe_snapshot(frames, asset=market)
            regime = build_technical_regime(snapshots)
            states[market] = market_state_from_technical(
                market, snapshots, regime, providers=providers, now=now
            )
        except Exception as exc:
            errors[market] = str(exc)
    return states, errors
