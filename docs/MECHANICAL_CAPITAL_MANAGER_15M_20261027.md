# Mechanical Capital Manager 15m — PAPER release candidate (2026-10-27)

## Requested rule
Keep micro-execution independent. Every 15m change an instance's requested
allocation by +10 percentage points of the manual slider cap per +1% independent
PAPER strategy return over the last 15m, or -10 points for -1%. Stop target
allocation at 0 when the independent strategy shadow is -10% from its tracked
peak. Keep tracking the shadow even at 0. Restart at 10% of the manual cap after
two consecutive positive independent shadow quarters and a positive 60m shadow
window. No AI required.

## What is actually implemented
- Pure mechanical_capital_manager_v1.py: causal 15m allocation; peak drawdown,
  gap pause, manual cap enforcement, 0% state, observed-shadow recovery, pair
  correlations, one-step-lagged comparison to a fixed-neutral allocation.
- Pure mechanical_capital_manager_observer_v1.py: four existing V3 strategy
  decision functions (MACD+Stoch V2.1, V2, rhythm build, MACD Flip) replayed
  from exact 1m subscribed canonical OHLC. 15m 1x PAPER marks remain independent
  of any real account or its actual allocation, even if suggested allocation=0.
- Analyse > Mekanisk kapitalmanager page: reads up to 4 exact matching V3
  instances' existing manually set slider caps, shows 15m suggested weights,
  1x shadow/manager vs fixed neutral comparison, correlation and JSON export.
  On-demand user click only, NOT a scheduled management job.
- NO changes to LIVE worker, order engine, margin, risk gates, account arming,
  stored V3 execution_policy, Saxo connector, source subscriptions or ownership.
  In particular this PR does not automatically move anyone's real sliders.

## Critical existing slider limitation
Current V3 execution_policy only accepts exposure_pct > 0, its UI slider is
1..100, and it limits new OPEN/ADD orders only. A smaller cap does NOT
automatically reduce already held exposure. A real target 0 requires a
distinct guarded, broker-confirmed CLOSE path with exact account/position,
pending order locks, reconciliation and margin, not merely writing 0 to DB.

## Research and risk limitations
The 1x shadow marks are constructed from closed OHLC without real Saxo fills,
contract multipliers, CFD leverage, slippage, margin usage, FX conversion,
funding or actual bid/ask spread. A user-configurable hypothetical cost
is applied; this remains only a directional scenario and NOT broker equity.
This approximation must NOT govern actual LIVE capital before being
validated/replaced by fully reconciled net strategy performance.

Account TotalValue is not flow-adjusted strategy performance: do not feed
raw Saxo NAV (deposits, FX, manual trades, other product, financing) into
a real allocator. A 15m -10% sampled stop cannot guarantee a -10% max loss;
losses can jump or continue while waiting for the next decision or a fill.
Four clones of V2.1 do not diversify; overlap/correlation must be evaluated.

## Next separately approved release gates
1. Validate the exact 15m observer against real strategy epochs, fills and
   broker-cost-adjusted returns, at comparable exposure and account currency.
2. Add persistent, autonomous PAPER per-instance observers on a dedicated
   idempotent 15m scheduler; the current UI replay does not run unattended.
3. Build safe fixed notional/pct effective override, global Saxo margin and
   correlated-cluster caps, min-lot rounding, and explicit broker-close handling
   for zero without deleting pending or risk guards.
4. Backtest out-of-sample versus fixed-cap and rhythm-aware allocation, then
   user-opt-in for LIVE only after sufficient controls, performance evidence
   and a dedicated gated rollout.
