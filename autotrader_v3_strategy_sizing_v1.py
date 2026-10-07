from __future__ import annotations

"""Resolve pure V3 strategy amount parameters from Saxo instrument rules.

The strategy owns behavior in *tranches*. Saxo owns what one legal amount tranche is.
This keeps strategy semantics independent from a Tech100-specific 0.01 assumption.
"""

from autotrader_open_sizing_v2 import EntryInstrumentRulesV2, minimum_legal_amount_v2
from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_macd_histogram_v1 import (
    STRATEGY_KEY_V3 as HISTOGRAM_KEY,
    MacdHistogramConfigV3,
)
from autotrader_v3_macd_histogram_flip_build_v1 import (
    STRATEGY_KEY_V3 as HISTOGRAM_FLIP_BUILD_KEY,
)
from autotrader_v3_macd_stoch_v1 import STRATEGY_KEY_V3 as STOCH_KEY
from autotrader_v3_vwap_regime_histogram_v1 import STRATEGY_KEY_V3 as VWAP_REGIME_KEY
from autotrader_v3_macd_trailing_v1 import (
    STRATEGY_KEY_V3 as TRAILING_KEY,
    MacdTrailingConfigV3,
)

DEFAULT_MAX_TRANCHES_V3 = 10


def strategy_amount_config_v3(
    *,
    strategy_key: str,
    rules: EntryInstrumentRulesV2,
    max_tranches: int = DEFAULT_MAX_TRANCHES_V3,
):
    """Return the amount config for one runtime strategy and exact Saxo product.

    V3's current inventory domain has 0.01 precision. Fail closed rather than
    silently rounding an instrument that needs finer amount precision.
    """

    count = int(max_tranches)
    if count <= 0:
        raise ValueError("max_tranches must be positive")

    tranche = float(minimum_legal_amount_v2(rules))
    canonical = TargetInventoryV3(tranche).amount
    if abs(canonical - tranche) > 1e-9:
        raise ValueError(
            f"Saxo legal amount {tranche:g} is finer than V3 inventory precision"
        )
    maximum = tranche * count

    if strategy_key in {TRAILING_KEY, STOCH_KEY}:
        return MacdTrailingConfigV3(tranche=tranche, max_inventory=maximum)
    if strategy_key in {HISTOGRAM_KEY, HISTOGRAM_FLIP_BUILD_KEY, VWAP_REGIME_KEY}:
        return MacdHistogramConfigV3(tranche=tranche, max_inventory=maximum)
    raise ValueError(f"unsupported V3 amount-config strategy: {strategy_key}")


__all__ = ["DEFAULT_MAX_TRANCHES_V3", "strategy_amount_config_v3"]
