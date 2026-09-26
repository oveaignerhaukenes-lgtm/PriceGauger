# Rabid Dog — cost-aware price chase, shadow only

This experimental NAS100 strategy reacts to the Saxo tradable bid/ask stream,
not completed MACD or stochastic candles. It tracks each observed high/low and
reverses after price changes far enough in the opposite direction. The change
threshold is the maximum of three points, three times current spread, and
three times the median recent one-second move. A wider/noisier market thus
needs a wider turn before reversing. The threshold is **hysteresis**, not a
smoothed indicator or an estimate of future returns.

One hypothetical 0.01 entry is recorded from FLAT; a direct long-to-short or
short-to-long flip has hypothetical order amount 0.02 and counts as **one**
order. The rolling budget is 100 hypothetical orders/hour, including an order
reserved for FLAT when 99 have been used. It also enforces at least one second
between proposed orders, a max spread of five points, and FLAT on a quote gap.
Tradability comes from the same Saxo bid/ask gates as Hunter. The log records
transition direction, size, count and cumulative simulated points using bid
for sales and ask for purchases.

This is **not connected to Saxo order execution**. The existing PG execution
path still waits for confirmed FLAT; it does not submit a 0.02 netting order.
The shadow state is in memory and resets on deployment; it does not establish
broker ownership, preserve quota across restarts, account for fill latency,
overnight risk, funding or fees beyond the observed spread. The shadow
performance cannot establish profitability or compliance with a real account
order cap. Before live promotion, persist quote, intent, attempts, fills and
rolling broker-side order quota across restarts and reconcile exact exposure.
