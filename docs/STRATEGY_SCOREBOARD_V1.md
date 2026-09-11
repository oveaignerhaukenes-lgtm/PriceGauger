# Strategy Scoreboard v1

Strategy Scoreboard compares the compact AutoTrader models on the same canonical 1m history and the same Hybrid Lab cost assumption.

## Windows

- 6h
- 24h
- 7d

For each model the scoreboard reports normalized signal return, max drawdown and 24h switch count. The benchmark set is MACD1, MACD2, MACD5, MACD2-10, MACD2-S, MACD-A and HYBRID.

## Regime labels

The regime indicator is deliberately simple and diagnostic rather than predictive:

- CHOPPY: low net progress and frequent direction changes.
- EVEN: balanced/ordered flow that does not satisfy an extreme regime rule.
- TREND: high directional efficiency and limited reversal density.
- IMPULSE: a large share of total movement is concentrated in a few bars.

The current 6h/24h/7d windows receive a regime label. The last 7 days are also split into hourly blocks so each strategy's replay return can be attributed to CHOPPY, EVEN, TREND and IMPULSE blocks.

## Safety boundary

The scoreboard is analysis-only. It does not switch LIVE strategy, submit manual targets or place Saxo orders. Promotion from an observed winner into LIVE remains a separate explicit decision.
