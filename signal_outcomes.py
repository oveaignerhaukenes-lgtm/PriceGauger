from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha1
from pathlib import Path
from typing import Iterable

import pandas as pd

from asset_state_mapping import AssetRecommendation
from market_data import MarketRequest, YahooProvider, fetch_market_data
from market_interpretation import MarketInterpretation

ASSET_SYMBOLS = {
    "Brent": "BZ=F",
    "Gold": "GC=F",
    "Silver": "SI=F",
    "DXY": "DX-Y.NYB",
}


@dataclass(frozen=True, slots=True)
class SignalOutcome:
    signal_id: str
    event_id: str
    asset: str
    direction: str
    score: float
    signal_strength: int
    created_at: str
    model_version: str
    prompt_version: str
    price_at_signal: float | None = None
    price_1h: float | None = None
    price_4h: float | None = None
    return_1h_pct: float | None = None
    return_4h_pct: float | None = None
    mfe_4h_pct: float | None = None
    mae_4h_pct: float | None = None
    price_provider: str | None = None

    def to_record(self) -> dict:
        return asdict(self)


class SignalOutcomeStore:
    def __init__(self, path: str | Path = "pricegauger.db") -> None:
        self.path = str(path)
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS signal_outcomes (
                    signal_id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL,
                    asset TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def save(self, item: SignalOutcome) -> None:
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO signal_outcomes(signal_id, event_id, asset, created_at, payload_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(signal_id) DO UPDATE SET payload_json=excluded.payload_json
                """,
                (item.signal_id, item.event_id, item.asset, item.created_at, json.dumps(item.to_record(), sort_keys=True)),
            )

    def load_all(self) -> list[SignalOutcome]:
        with self._connect() as db:
            rows = db.execute("SELECT payload_json FROM signal_outcomes ORDER BY created_at DESC").fetchall()
        return [SignalOutcome(**json.loads(row["payload_json"])) for row in rows]

    def get(self, signal_id: str) -> SignalOutcome | None:
        with self._connect() as db:
            row = db.execute("SELECT payload_json FROM signal_outcomes WHERE signal_id=?", (signal_id,)).fetchone()
        return SignalOutcome(**json.loads(row["payload_json"])) if row else None


def _signal_id(interpretation: MarketInterpretation, asset: str) -> str:
    seed = "|".join((interpretation.event_id, asset, interpretation.model_version, interpretation.prompt_version))
    return "signal:" + sha1(seed.encode("utf-8")).hexdigest()[:24]


def register_recommendations(
    interpretation: MarketInterpretation,
    recommendations: Iterable[AssetRecommendation],
    *,
    store: SignalOutcomeStore | None = None,
    created_at: datetime | None = None,
) -> list[SignalOutcome]:
    store = store or SignalOutcomeStore()
    now = (created_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    created: list[SignalOutcome] = []
    for recommendation in recommendations:
        signal_id = _signal_id(interpretation, recommendation.asset)
        existing = store.get(signal_id)
        if existing is not None:
            created.append(existing)
            continue
        item = SignalOutcome(
            signal_id=signal_id,
            event_id=interpretation.event_id,
            asset=recommendation.asset,
            direction=recommendation.direction,
            score=recommendation.score,
            signal_strength=recommendation.signal_strength,
            created_at=now,
            model_version=interpretation.model_version,
            prompt_version=interpretation.prompt_version,
        )
        store.save(item)
        created.append(item)
    return created


def _market_frame(asset: str) -> tuple[pd.DataFrame, str]:
    symbol = ASSET_SYMBOLS[asset]
    request = MarketRequest(asset, "5min", 2000, {"yahoo": symbol})
    result = fetch_market_data(request, [YahooProvider()])
    return result.frame, result.provider_name


def _close_near(frame: pd.DataFrame, target: pd.Timestamp) -> float | None:
    after = frame[frame["timestamp"] >= target]
    if after.empty:
        return None
    return float(after.iloc[0]["close"])


def refresh_signal_outcomes(
    *,
    store: SignalOutcomeStore | None = None,
    now: datetime | None = None,
) -> list[SignalOutcome]:
    store = store or SignalOutcomeStore()
    current = pd.Timestamp(now or datetime.now(timezone.utc))
    updated: list[SignalOutcome] = []
    by_asset: dict[str, tuple[pd.DataFrame, str]] = {}
    for item in store.load_all():
        created = pd.Timestamp(item.created_at)
        if created.tzinfo is None:
            created = created.tz_localize("UTC")
        needs_data = item.price_at_signal is None or (current >= created + pd.Timedelta(hours=1) and item.price_1h is None) or (current >= created + pd.Timedelta(hours=4) and item.price_4h is None)
        if not needs_data:
            updated.append(item)
            continue
        try:
            frame, provider = by_asset.setdefault(item.asset, _market_frame(item.asset))
        except Exception:
            updated.append(item)
            continue
        entry = item.price_at_signal or _close_near(frame, created)
        price_1h = item.price_1h
        price_4h = item.price_4h
        if current >= created + pd.Timedelta(hours=1):
            price_1h = price_1h or _close_near(frame, created + pd.Timedelta(hours=1))
        if current >= created + pd.Timedelta(hours=4):
            price_4h = price_4h or _close_near(frame, created + pd.Timedelta(hours=4))
        return_1h = ((price_1h / entry) - 1.0) * 100.0 if entry and price_1h else None
        return_4h = ((price_4h / entry) - 1.0) * 100.0 if entry and price_4h else None
        mfe = mae = None
        if entry and current >= created + pd.Timedelta(hours=4):
            window = frame[(frame["timestamp"] >= created) & (frame["timestamp"] <= created + pd.Timedelta(hours=4))]
            if not window.empty:
                high = float(window["high"].max()) if "high" in window else float(window["close"].max())
                low = float(window["low"].min()) if "low" in window else float(window["close"].min())
                sign = -1.0 if item.direction == "SHORT" else 1.0
                favourable = ((high / entry) - 1.0) * 100.0 if sign > 0 else ((entry / low) - 1.0) * 100.0
                adverse = ((low / entry) - 1.0) * 100.0 if sign > 0 else ((entry / high) - 1.0) * 100.0
                mfe, mae = favourable, adverse
        replacement = SignalOutcome(
            **{
                **item.to_record(),
                "price_at_signal": entry,
                "price_1h": price_1h,
                "price_4h": price_4h,
                "return_1h_pct": return_1h,
                "return_4h_pct": return_4h,
                "mfe_4h_pct": mfe,
                "mae_4h_pct": mae,
                "price_provider": provider,
            }
        )
        store.save(replacement)
        updated.append(replacement)
    return updated
