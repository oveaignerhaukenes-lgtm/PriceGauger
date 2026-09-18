from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True, slots=True)
class PositionManagerConfigV1:
    """Analysis-only stateful position-management settings.

    Percent values are decimal returns: 0.0015 == 0.15%.
    The manager consumes an existing PRICE/TARGET signal frame. It does not create
    market opinions and has no execution or broker authority.
    """

    reversal_confirm_bars: int = 3
    reentry_cooldown_bars: int = 3
    reentry_confirm_bars: int = 2
    min_hold_bars: int = 3
    volatility_lookback: int = 30
    arm_vol_multiple: float = 2.0
    min_arm_pct: float = 0.0015
    max_giveback_fraction: float = 0.25


DEFAULT_POSITION_MANAGER_CONFIG_V1 = PositionManagerConfigV1()


def _bounded_config(config: PositionManagerConfigV1) -> PositionManagerConfigV1:
    return PositionManagerConfigV1(
        reversal_confirm_bars=max(1, int(config.reversal_confirm_bars)),
        reentry_cooldown_bars=max(0, int(config.reentry_cooldown_bars)),
        reentry_confirm_bars=max(1, int(config.reentry_confirm_bars)),
        min_hold_bars=max(0, int(config.min_hold_bars)),
        volatility_lookback=max(5, int(config.volatility_lookback)),
        arm_vol_multiple=max(0.0, float(config.arm_vol_multiple)),
        min_arm_pct=max(0.0, float(config.min_arm_pct)),
        max_giveback_fraction=max(0.05, min(0.95, float(config.max_giveback_fraction))),
    )


def apply_position_manager_v1(
    frame: pd.DataFrame,
    *,
    config: PositionManagerConfigV1 = DEFAULT_POSITION_MANAGER_CONFIG_V1,
) -> pd.DataFrame:
    """Apply stateful management to an existing directional target series.

    Design goals for the first shadow/lab version:
    - keep weak one-bar reversals from flipping a position immediately;
    - remember entry price and maximum favourable excursion (MFE);
    - after a meaningful favourable move, flatten if too much of the peak is given back;
    - require a short cooldown/confirmation before same-direction re-entry after a
      profit-lock exit.

    This is deliberately analysis-only. It never sends orders and does not alter the
    upstream signal generator.
    """
    if frame.empty:
        result = frame.copy()
        result["RAW_TARGET"] = pd.Series(dtype="float64")
        result["MANAGER_REASON"] = pd.Series(dtype="object")
        result["MFE_PCT"] = pd.Series(dtype="float64")
        result["ACTIVE_PNL_PCT"] = pd.Series(dtype="float64")
        result["TRAIL_ARM_PCT"] = pd.Series(dtype="float64")
        return result
    missing = [name for name in ("PRICE", "TARGET") if name not in frame.columns]
    if missing:
        raise ValueError(f"position manager missing columns: {missing}")

    cfg = _bounded_config(config)
    result = frame.copy()
    raw_target = result["TARGET"].fillna(0.0).astype("float64")
    authoritative_cross = (
        result["AUTHORITATIVE_CROSS"].fillna(0.0).astype("float64")
        if "AUTHORITATIVE_CROSS" in result.columns
        else pd.Series(0.0, index=result.index, dtype="float64")
    )
    price = result["PRICE"].astype("float64")
    minute_returns = price.pct_change()
    rolling_vol = minute_returns.rolling(
        cfg.volatility_lookback,
        min_periods=min(10, cfg.volatility_lookback),
    ).std().fillna(0.0)

    managed = 0
    entry_price: float | None = None
    active_bars = 0
    mfe = 0.0
    reversal_direction = 0
    reversal_count = 0
    cooldown_remaining = 0
    blocked_reentry_direction = 0
    reentry_count = 0

    targets: list[float] = []
    reasons: list[str] = []
    mfe_values: list[float] = []
    pnl_values: list[float] = []
    arm_values: list[float] = []

    def enter(direction: int, current_price: float) -> None:
        nonlocal managed, entry_price, active_bars, mfe
        nonlocal reversal_direction, reversal_count, blocked_reentry_direction, reentry_count
        managed = int(direction)
        entry_price = float(current_price)
        active_bars = 0
        mfe = 0.0
        reversal_direction = 0
        reversal_count = 0
        blocked_reentry_direction = 0
        reentry_count = 0

    for index in range(len(result)):
        current_price = float(price.iloc[index])
        base_target = int(raw_target.iloc[index])
        if base_target not in (-1, 0, 1):
            base_target = 0
        cross_target = int(authoritative_cross.iloc[index])
        if cross_target not in (-1, 0, 1):
            cross_target = 0
        if cooldown_remaining > 0:
            cooldown_remaining -= 1

        reason = "hold"
        current_pnl = 0.0
        arm = max(cfg.min_arm_pct, cfg.arm_vol_multiple * float(rolling_vol.iloc[index]))

        if managed == 0:
            if cross_target in (-1, 1):
                # Confirmed closed 5m MACD cross overrides cooldown/re-entry delay.
                enter(cross_target, current_price)
                reason = "authoritative_cross"
            elif base_target in (-1, 1):
                if blocked_reentry_direction == base_target:
                    if cooldown_remaining <= 0:
                        reentry_count += 1
                    else:
                        reentry_count = 0
                    if cooldown_remaining <= 0 and reentry_count >= cfg.reentry_confirm_bars:
                        enter(base_target, current_price)
                        reason = "reentry"
                    else:
                        reason = "reentry_wait"
                else:
                    enter(base_target, current_price)
                    reason = "entry"
            else:
                reentry_count = 0
        else:
            active_bars += 1
            if entry_price is not None and entry_price > 0.0:
                current_pnl = managed * ((current_price / entry_price) - 1.0)
                mfe = max(mfe, current_pnl)

            if cross_target in (-1, 1):
                # If the supervisor anticipated the move before 5m confirms it, keep
                # the existing entry/MFE. If 5m confirms the opposite direction,
                # reverse immediately; management may never lag the confirmed cross.
                if cross_target == managed:
                    reversal_direction = 0
                    reversal_count = 0
                    reason = "authoritative_cross_hold"
                else:
                    enter(cross_target, current_price)
                    reason = "authoritative_cross"
            else:
                if base_target == -managed:
                    if reversal_direction == base_target:
                        reversal_count += 1
                    else:
                        reversal_direction = base_target
                        reversal_count = 1
                else:
                    reversal_direction = 0
                    reversal_count = 0

                profit_lock_armed = active_bars >= cfg.min_hold_bars and mfe >= arm and mfe > 0.0
                giveback_triggered = profit_lock_armed and current_pnl <= mfe * (1.0 - cfg.max_giveback_fraction)

                if giveback_triggered:
                    previous_direction = managed
                    managed = 0
                    entry_price = None
                    active_bars = 0
                    cooldown_remaining = cfg.reentry_cooldown_bars
                    blocked_reentry_direction = previous_direction
                    reentry_count = 0
                    reversal_direction = 0
                    reversal_count = 0
                    reason = "profit_lock"
                elif reversal_count >= cfg.reversal_confirm_bars:
                    enter(base_target, current_price)
                    reason = "confirmed_reversal"
                elif base_target == 0:
                    reason = "hold_neutral"

        targets.append(float(managed))
        reasons.append(reason)
        mfe_values.append(float(mfe if managed != 0 else 0.0))
        pnl_values.append(float(current_pnl if managed != 0 else 0.0))
        arm_values.append(float(arm))

    result["RAW_TARGET"] = raw_target
    result["TARGET"] = pd.Series(targets, index=result.index, dtype="float64")
    result["MANAGER_REASON"] = pd.Series(reasons, index=result.index, dtype="object")
    result["MFE_PCT"] = pd.Series(mfe_values, index=result.index, dtype="float64")
    result["ACTIVE_PNL_PCT"] = pd.Series(pnl_values, index=result.index, dtype="float64")
    result["TRAIL_ARM_PCT"] = pd.Series(arm_values, index=result.index, dtype="float64")
    return result


__all__ = [
    "DEFAULT_POSITION_MANAGER_CONFIG_V1",
    "PositionManagerConfigV1",
    "apply_position_manager_v1",
]
