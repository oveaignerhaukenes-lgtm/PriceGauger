# AutoManager P/L comparison v2

This contract defines the bottom-of-TradingDesk P/L figure. It deliberately keeps
actual LIVE accounting separate from paper strategy replay while aligning both on
one shared time axis.

## Actual LIVE panel

- Source: `pg_v2_autotrader_pilot_equity_events` for the one exact LIVE pilot.
- Value: cumulative, authoritative, settled Saxo net realized P/L.
- Normalization: percent of the isolated pilot seed capital.
- Shape: step curve from cohort start through each settled reconciliation event.
- Open/unrealized P/L is excluded. PriceGauger does not estimate a currency P/L
  from position percentages, margin, notional or the underlying-market move.

## Model panel

- Policies: MACD 30m long/flat, short/flat and long/short switch.
- Source: the exact canonical instrument's completed 1m history, aggregated to
  fully closed UTC-aligned 30m bars.
- Common basis: the observed starting exposure, cohort start, price baseline and
  pilot seed capital used by the LIVE enrollment.
- Value: mark-to-market paper equity at each closed 30m bar, normalized as percent
  of seed capital.
- Paper replay models no spread, slippage, fees, margin or execution latency.
- Paper policies remain read-only and receive no order or authoritative P/L-ledger
  authority.

## Interpretation boundary

The panels are intentionally separate. The LIVE panel answers "what has Saxo
authoritatively settled?" The model panel answers "how would each policy have
marked to market on the same canonical 30m path?" They share time and normalization,
but a paper line must not be presented as actual Saxo P/L and unsettled LIVE P/L
must not be fabricated to make the curves look point-by-point equivalent.
