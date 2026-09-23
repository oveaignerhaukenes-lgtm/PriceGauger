from __future__ import annotations
from datetime import datetime,timedelta,timezone
from autotrader_mtf_entry_shadow_v2 import closed_bars_v2,macd_observations_v2
from autotrader_strategy_enrollment_v2 import load_active_strategy_enrollments_v2
from autotrader_v3_closed_bar_driver_v1 import evaluate_closed_bar_once_v3
from autotrader_v3_macd_trailing_v1 import STRATEGY_KEY_V3
from autotrader_v3_sim_authority_v1 import sim_authority_armed_v3
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2

def run_v3_macd_trailing_sim_cycle_v1(*,db_path="pricegauger.db",now=None)->int:
    """Evaluate armed v3 SIM traders once per completed 5m bar. No broker POST here yet."""
    processed=0
    end=now or datetime.now(timezone.utc)
    for e in load_active_strategy_enrollments_v2():
        if e.strategy_key != STRATEGY_KEY_V3 or not sim_authority_armed_v3(e.pilot_key,db_path=db_path):
            continue
        bars=CanonicalMarketBarStoreV2(db_path).load_instrument_range(
            instrument_id=e.instrument_id,start=end-timedelta(days=14),end=end,limit=20000)
        if not bars: continue
        closed=closed_bars_v2(tuple(b.point for b in bars),market=e.market_name,timeframe_minutes=5)
        obs=macd_observations_v2(closed,timeframe_minutes=5)
        if not obs: continue
        result=evaluate_closed_bar_once_v3(trader_id=e.pilot_key,observation=obs[-1],db_path=db_path)
        processed += int(result.is_new)
    return processed
