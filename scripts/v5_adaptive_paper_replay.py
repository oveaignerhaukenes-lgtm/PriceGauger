"""Reproducible offline comparison of fixed V3 and bounded online V5.

Example:
  python scripts/v5_adaptive_paper_replay.py --phase train \
    --split-date 2026-11-20 ./v3_2026-11-16.json ./v3_2026-11-17.json

The immutable date split prevents accidental evaluation of holdout data while
choosing a candidate. No external API, account access, or broker orders.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autotrader_v3_macd_stoch_v21_split_v3 import (  # noqa: E402
    LONG_KEY_V3_PRICE_HIST, SHORT_KEY_V3_PRICE_HIST,
)
from autotrader_v3_split_v5_adaptive_research import (  # noqa: E402
    AdaptiveV5Paper, POLICIES_V5,
)
from strategy_lab_v2_replay import (  # noqa: E402
    PURE_V3, ReplayCostsV2, replay_v3_strategy_v2,
)


def replay_one_file(path: Path, *, policy, spread_bps: float):
    doc = json.loads(path.read_text(encoding="utf-8"))
    market = str(doc["provenance"]["market"])
    bars = [SimpleNamespace(
        market_name=market, market=market,
        bar_time=datetime.fromisoformat(row["time"]),
        open=row["open"], high=row["high"], low=row["low"],
        close=row["close"], volume=row.get("volume"),
    ) for row in doc["raw_saxo_1m_ohlc"]]
    costs = ReplayCostsV2(point_value_nok=10, spread_bps=spread_bps,
                          variable_fee_bps=0, fixed_fee_nok=0)
    result = []
    for key, side in ((LONG_KEY_V3_PRICE_HIST, 1),
                      (SHORT_KEY_V3_PRICE_HIST, -1)):
        original = PURE_V3[key]
        # The V5 policy's round-trip estimate must use the same assumed costs
        # as the replay executor. This changes no execution or broker logic.
        configured = (None if policy is None else type(policy)(**{
            k: (spread_bps if k == "spread_bps_roundtrip" else getattr(policy, k))
            for k in policy.__dataclass_fields__
        }))
        model = original if configured is None else AdaptiveV5Paper(
            side=side, policy=configured)
        try:
            PURE_V3[key] = model
            paper = replay_v3_strategy_v2(
                strategy_key=key, bars=bars, costs=costs,
                timeframe="1m", regime_timeframe="5m", exit_timeframe="2m")
        finally:
            PURE_V3[key] = original
        result.append(dict(
            source=path.name, side="LONG" if side == 1 else "SHORT",
            model="V3" if policy is None else "V5-"+policy.name,
            return_pct=round(paper.net_return_pct, 6),
            max_drawdown_pct=round(paper.drawdown_pct, 6),
            events=paper.trades, cost_nok=round(paper.total_cost_nok, 2),
            guards=0 if policy is None else model.gates,
            completed_round_trips=(None if policy is None else model.paper_round_trips),
        ))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("train", "holdout"), required=True)
    parser.add_argument("--split-date", required=True,
                        help="First day reserved as untouched holdout: YYYY-MM-DD")
    parser.add_argument("--spread-bps", type=float, default=4.)
    parser.add_argument("--policy", choices=("all",)+tuple(
                        p.name for p in POLICIES_V5), default="all")
    parser.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args()
    split = date.fromisoformat(args.split_date)
    if not (0 <= args.spread_bps <= 50):
        parser.error("Specify explicit realistic spread from 0 to 50bp")
    for path in args.files:
        # All rows are independently validated against the declared partition
        # to prevent a misleading file name bypassing the date guard.
        doc = json.loads(path.read_text(encoding="utf-8"))
        dates = {datetime.fromisoformat(row["time"]).date()
                 for row in doc["raw_saxo_1m_ohlc"]}
        if not dates or any((d >= split) != (args.phase == "holdout") for d in dates):
            parser.error(f"{path.name}: data outside {args.phase} partition")
    policies = (None,)+tuple(p for p in POLICIES_V5
                            if args.policy in ("all", p.name))
    for path in args.files:
        for policy in policies:
            for record in replay_one_file(path, policy=policy,
                                          spread_bps=args.spread_bps):
                print(json.dumps(record, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
