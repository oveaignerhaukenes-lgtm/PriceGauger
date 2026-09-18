from __future__ import annotations

import pandas as pd

from autotrader_position_manager_replay_v1 import PositionManagerConfigV1, apply_position_manager_v1


def _frame(prices, targets) -> pd.DataFrame:
    index = pd.date_range("2026-09-16T00:00:00Z", periods=len(prices), freq="min")
    return pd.DataFrame({"PRICE": prices, "TARGET": targets}, index=index)


def test_manager_requires_confirmed_reversal() -> None:
    frame = _frame(
        [100.0, 100.0, 100.0, 100.0, 100.0, 100.0],
        [1, -1, 1, -1, -1, -1],
    )
    managed = apply_position_manager_v1(
        frame,
        config=PositionManagerConfigV1(
            reversal_confirm_bars=3,
            min_arm_pct=1.0,
            arm_vol_multiple=0.0,
        ),
    )
    assert list(managed["TARGET"]) == [1.0, 1.0, 1.0, 1.0, 1.0, -1.0]
    assert managed["MANAGER_REASON"].iloc[-1] == "confirmed_reversal"


def test_manager_locks_profit_after_meaningful_giveback() -> None:
    frame = _frame(
        [100.0, 100.2, 100.5, 101.0, 100.70, 100.60],
        [1, 1, 1, 1, 1, 1],
    )
    managed = apply_position_manager_v1(
        frame,
        config=PositionManagerConfigV1(
            min_hold_bars=1,
            min_arm_pct=0.002,
            arm_vol_multiple=0.0,
            max_giveback_fraction=0.25,
            reentry_cooldown_bars=3,
            reentry_confirm_bars=2,
        ),
    )
    assert managed["TARGET"].iloc[3] == 1.0
    assert managed["TARGET"].iloc[4] == 0.0
    assert managed["MANAGER_REASON"].iloc[4] == "profit_lock"
    assert managed["TARGET"].iloc[5] == 0.0


def test_manager_does_not_mutate_raw_signal_column() -> None:
    frame = _frame([100.0, 100.1, 100.2], [1, 1, -1])
    managed = apply_position_manager_v1(frame)
    assert list(managed["RAW_TARGET"]) == [1.0, 1.0, -1.0]
    assert list(frame["TARGET"]) == [1, 1, -1]


def test_manager_module_has_no_execution_authority() -> None:
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "autotrader_position_manager_replay_v1.py").read_text(encoding="utf-8").lower()
    for token in (
        "import saxo",
        "from saxo",
        "order_request",
        "request_manual_target",
        "persist_intent",
        "client.post(",
        "requests.post(",
    ):
        assert token not in source


def test_authoritative_cross_bypasses_reversal_confirmation_and_cooldown() -> None:
    frame = _frame(
        [100.0, 100.0, 100.0],
        [-1, 1, 1],
    )
    frame["AUTHORITATIVE_CROSS"] = [0, 1, 0]
    managed = apply_position_manager_v1(
        frame,
        config=PositionManagerConfigV1(
            reversal_confirm_bars=3,
            reentry_cooldown_bars=5,
            reentry_confirm_bars=3,
            min_arm_pct=1.0,
            arm_vol_multiple=0.0,
        ),
    )
    assert list(managed["TARGET"]) == [-1.0, 1.0, 1.0]
    assert managed["MANAGER_REASON"].iloc[1] == "authoritative_cross"
