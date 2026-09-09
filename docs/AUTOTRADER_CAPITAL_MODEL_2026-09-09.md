# AutoTrader pilot capital model — 2026-09-09

## Current benchmark contract

- Each AutoTrader product capital lineage starts with one isolated original seed.
- Active cohort equity is `cohort seed capital + settled realized net P/L`.
- Strategy hot-switches create immutable activation cohorts and seed the new cohort from the source cohort's current settled equity; this preserves compounding without reviving old strategy runtime state.
- Capital-risk reporting walks the strategy-switch lineage back to the original cohort, so the original seed remains the economic loss boundary even after strategy switches.
- Unrelated Saxo deposits, cash, and other pilots do not enlarge this budget.
- Simple LIVE MACD uses `MAX_WITHIN_PILOT`: largest legal entry supported by the current pilot equity, explicit product admission, Saxo precheck, and the pilot Margin Envelope.
- Reversal remains `CLOSE -> broker-confirmed FLAT -> OPEN opposite`.
- The next OPEN reloads current pilot equity, so settled profit compounds and settled loss reduces the next budget.

## Status / observability

TradingDesk should expose a compact pilot panel with:

- original seed for the continuous capital lineage;
- current active-cohort equity;
- total settled capital gain/loss relative to the original seed;
- reconciled closed-trade count, wins/losses/breakeven, and win rate across the lineage;
- current Saxo direction/amount;
- latest OPEN amount, pilot budget, precheck initial margin, and utilization of pilot budget;
- future harvest threshold.

Only durable PG/Saxo reconciliation data is used. The status panel has no execution authority.

## Future harvesting policy — not implemented yet

The intended capital policy is:

1. do not harvest while capital-lineage equity is below `2 x original seed`;
2. after the lineage has doubled, harvest 20% of positive realized profit according to an explicitly versioned rule;
3. harvested capital leaves AutoTrader-controlled equity and is moved to an isolated reserve account;
4. the reserve should first accumulate at least the original seed, so a failed pilot can be restarted without new outside capital;
5. reserve capital may continue to grow independently after the initial seed has been recovered.

A future implementation must define the exact realization interval/basis for the 20% harvest and must never infer a transfer from unrealized P/L. Broker transfers require a separate explicit authority boundary from trading execution.
