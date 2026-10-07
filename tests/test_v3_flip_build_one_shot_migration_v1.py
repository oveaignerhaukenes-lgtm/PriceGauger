from pathlib import Path

import pytest

from autotrader_v3_config_v1 import AutoTraderConfigV3, load_autotrader_config_v3, save_autotrader_config_v3
from autotrader_v3_ops_migrate_flip_build_20261007 import (
    TRADER_ID,
    migrate_nas100_flip_build_once_v1,
)


def test_one_shot_migration_switches_only_strategy_and_preserves_config(tmp_path):
    db = str(tmp_path / "pg.db")
    original = AutoTraderConfigV3(
        trader_id=TRADER_ID,
        strategy_key="macd-histogram",
        timeframe="2m",
        control_mode="Manuell",
        modifiers=("reset-on-loss",),
    )
    save_autotrader_config_v3(original, db_path=db)

    assert migrate_nas100_flip_build_once_v1(db_path=db) == "switched"
    updated = load_autotrader_config_v3(TRADER_ID, db_path=db)
    assert updated.strategy_key == "macd-histogram-flip-build"
    assert updated.timeframe == "2m"
    assert updated.control_mode == "Manuell"
    assert updated.modifiers == ("reset-on-loss",)
    assert migrate_nas100_flip_build_once_v1(db_path=db) == "already_switched"


def test_one_shot_migration_fails_closed_on_unexpected_config(tmp_path):
    db = str(tmp_path / "pg.db")
    save_autotrader_config_v3(
        AutoTraderConfigV3(
            trader_id=TRADER_ID,
            strategy_key="macd",
            timeframe="2m",
        ),
        db_path=db,
    )
    with pytest.raises(RuntimeError, match="unexpected strategy"):
        migrate_nas100_flip_build_once_v1(db_path=db)


def test_worker_runs_migration_before_fast_loop():
    source = Path("worker.py").read_text(encoding="utf-8")
    assert source.index("migrate_nas100_flip_build_once_v1") < source.index(
        'LOGGER.info("v3 LIVE fast loop started'
    )
