"""Read-only NFP reaction probe. No trading endpoints or broker-side persistence.

Run inside the PriceGauger environment (requires verified instrument UICs):
  python -m nfp_saxo_probe --events events.json --instruments instruments.json

events.json: [{"date":"2026-10-02","release_utc":"2026-10-02T12:30:00Z"}, ...]
instruments.json: {"Gold":{"uic":123,"asset_type":"CfdOnFutures"}, ...}
Required: Gold, Tech100. Optional: US2Y, US10Y, DXY, SP500.
UIC/asset types must be verified against Saxo, not inferred from symbol names.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
from saxo_provider import SaxoInstrument, configured_client

HORIZONS = (5, 10, 15, 30)
SIGNAL_MINUTE = 1
ASSETS = ("Gold", "Tech100", "US2Y", "US10Y", "DXY", "SP500")


def reaction(frame: pd.DataFrame, release: pd.Timestamp) -> dict:
    """Pre-release baseline and completed-minute closes. Signal after 1m; enter next bar open."""
    if frame.empty:
        return {"status": "NO_DATA"}
    frame = frame.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame = frame.set_index("timestamp").sort_index()
    # Saxo bar timestamps denote the start of the minute.
    before = release - pd.Timedelta(minutes=1)
    if before not in frame.index:
        return {"status": "MISSING_BASELINE"}
    baseline = float(frame.loc[before, "close"])
    if baseline <= 0:
        return {"status": "INVALID_BASELINE"}
    result = {"status": "OK", "baseline": baseline}
    entry_time = release + pd.Timedelta(minutes=SIGNAL_MINUTE)
    result["entry_open"] = float(frame.loc[entry_time, "open"]) if entry_time in frame.index and "open" in frame.columns else None
    for minute in (SIGNAL_MINUTE, *HORIZONS):
        target = release + pd.Timedelta(minutes=minute - 1)
        if target not in frame.index:
            result[f"m{minute}"] = None
        else:
            result[f"m{minute}"] = (float(frame.loc[target, "close"]) / baseline - 1) * 100
    return result


def collect(client, events: list, instruments: dict) -> list[dict]:
    output = []
    for event in events:
        release = pd.Timestamp(event["release_utc"])
        if release.tzinfo is None:
            raise ValueError("release_utc must be timezone aware")
        release = release.tz_convert("UTC")
        row = {"date": event["date"], "release_utc": release.isoformat(), "assets": {}}
        for asset in ASSETS:
            if asset not in instruments:
                row["assets"][asset] = {"status": "NOT_CONFIGURED"}
                continue
            instrument = SaxoInstrument.from_mapping(asset, instruments[asset])
            try:
                # Saxo may reject old 1m history or expired contracts.
                bars = client.chart(instrument, horizon_minutes=1, count=45,
                                    time=release - pd.Timedelta(minutes=2), mode="From")
                row["assets"][asset] = reaction(bars, release)
            except Exception as exc:
                row["assets"][asset] = {"status": "FETCH_ERROR", "error_type": type(exc).__name__}
        gold = row["assets"]["Gold"]
        tech = row["assets"]["Tech100"]
        row["gold_signal_1m"] = None if gold.get("m1") is None else (
            1 if gold["m1"] > 0 else -1 if gold["m1"] < 0 else 0
        )
        row["tech_follow_gold"] = {}
        for h in HORIZONS:
            change = tech.get(f"m{h}")
            signal = row["gold_signal_1m"]
            entry = tech.get("entry_open")
            baseline = tech.get("baseline")
            if change is None or signal in (None, 0) or entry is None or entry <= 0 or baseline is None:
                row["tech_follow_gold"][f"m{h}"] = None
            else:
                exit_price = baseline * (1 + change / 100)
                gross = signal * (exit_price / entry - 1) * 100
                row["tech_follow_gold"][f"m{h}"] = {
                    "direction_correct": gross > 0,
                    "gross_directional_return_pct": gross,
                }
        output.append(row)
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--instruments", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("nfp_saxo_probe_results.json"))
    args = parser.parse_args()
    events = json.loads(args.events.read_text())
    instruments = json.loads(args.instruments.read_text())
    if not isinstance(events, list) or not isinstance(instruments, dict):
        raise ValueError("Invalid input format")
    if not {"Gold", "Tech100"}.issubset(instruments):
        raise ValueError("Gold and Tech100 instruments are required")
    client = configured_client()
    if client is None:
        raise RuntimeError("Saxo authentication unavailable")
    results = collect(client, events, instruments)
    args.output.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"Wrote {len(results)} events to {args.output}; missing data remain explicitly null")


if __name__ == "__main__":
    main()
