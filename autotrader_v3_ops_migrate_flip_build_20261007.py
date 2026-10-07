from __future__ import annotations

"""One-shot production migration for the NAS100 V3 pilot.

This module is intentionally temporary. It switches only the known NAS100 pilot
from the existing MACD Histogram strategy to Histogram Flip+Build while
preserving timeframe, control mode and modifiers. Any unexpected config fails
closed.
"""

from dataclasses import replace

from autotrader_v3_config_v1 import load_autotrader_config_v3, save_autotrader_config_v3

TRADER_ID = "b6008676-ec57-50e9-9cbf-3b0577c643ab"
SOURCE_STRATEGY = "macd-histogram"
TARGET_STRATEGY = "macd-histogram-flip-build"
EXPECTED_TIMEFRAME = "2m"


def migrate_nas100_flip_build_once_v1(*, db_path: str = "pricegauger.db") -> str:
    config = load_autotrader_config_v3(TRADER_ID, db_path=db_path)

    if config.strategy_key == TARGET_STRATEGY and config.timeframe == EXPECTED_TIMEFRAME:
        return "already_switched"

    if config.strategy_key != SOURCE_STRATEGY:
        raise RuntimeError(
            f"unexpected strategy for one-shot migration: {config.strategy_key}"
        )
    if config.timeframe != EXPECTED_TIMEFRAME:
        raise RuntimeError(
            f"unexpected timeframe for one-shot migration: {config.timeframe}"
        )

    updated = replace(config, strategy_key=TARGET_STRATEGY)
    save_autotrader_config_v3(updated, db_path=db_path)
    return "switched"


__all__ = ["migrate_nas100_flip_build_once_v1"]
