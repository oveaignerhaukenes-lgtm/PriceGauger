"""Fixed, explicitly opt-in Impulse Catcher exit variants for common BBO replay.

Entry criteria, one-sided inventory, urgent reversal exit and all broker gates
stay identical to v1.1. These thresholds are hypotheses, not tuned on fills.
"""
from __future__ import annotations

from dataclasses import replace

from autotrader_impulse_catcher_v1 import ImpulseCatcherConfig


def impulse_catcher_config(side: str, version: str) -> ImpulseCatcherConfig:
    base=ImpulseCatcherConfig(side=side,quote_gap_seconds=8.0)
    if version=="1.1":
        return base
    if version=="1.2":
        # Wait longer after the last favorable extreme, but retain the
        # unchanged urgent-reversal path and original retrace threshold.
        return replace(base,exhaustion_seconds=6.0)
    if version=="1.3":
        # Require persistent, noise-adjusted retrace after the same 6s stall;
        # a severe reversal still exits without the extra confirmation.
        return replace(base,exhaustion_seconds=6.0,
                       exit_noise_multiple=4.0,exit_confirmation_seconds=3.0)
    raise ValueError("Unknown Impulse Catcher patient-exit version")
