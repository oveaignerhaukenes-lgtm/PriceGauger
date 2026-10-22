# PriceTrend #1 — Tech100-only price regime research (2026-10-22)

**Status: PriceTrend #1 V3 LIVE route and SIM replay ready in code, subject to CI,
Railway deployment, exact Saxo instrument/risk verification and explicit
user-selected account/arming. No accounts auto-enabled.**
The pure SMA9/21 baseline remains SIM-only.

## Hypothesis

A gradual, persistent Tech100 decline should not be mistaken for a sideways
market because MACD histogram or Stochastic temporarily rises. **Price**
owns regime direction, not the derivatives of momentum.

## Causal inputs

Only valid, contiguous and **fully closed** 1-minute canonical Saxo OHLC from
exact market 'US Tech 100 NAS'. Construct aligned, completed 5m candles for the
regime and fully closed signal-period candles for entry timing.
Selectable fixed S periods: **1m, 2m, 5m, 10m, 15m, 30m and 1h**.
The 5m trend regime remains fixed across signal periods; selecting 1m
does not remove the higher-level trend filter. No volume requirement; VWAP is *not*
used while volume reliability is unverified. No AI calls, broker access or
additional data ingestion.

- 5m SMA 21 slope over three completed 5m bars, normalized by 14 x 5m ATR.
- 5m SMA 9 above/below SMA 21 and price offset from SMA 21 (0.10 ATR).
- 5m price structure: compare most recent 3 completed high/low bars against
  preceding 3 (LH/LL for BEAR, HH/HL for BULL, ATR noise tolerance).
- 5m directional efficiency over 12 completed closes:
  abs(last - first) / sum(abs(each consecutive difference)).
- Entry only when efficiency >= 0.35, SMA21 slope magnitude >= 0.08 ATR,
  SMA9/21 align, and completed **selected S** close/S SMA9 slope confirm direction.
- Single minimum Saxo-legal tranche. Initial research deliberately avoids
  pyramiding, to isolate whether **holding direction** is the actual advantage.
- In an existing SHORT, MACD becoming positive does not cause an exit. It
  persists through a 5m slowdown unless price breaches ATR trailing level,
  crosses 5m SMA21 + 0.5 ATR, or the 5m regime becomes BULL (mirrored LONG).
- ATR trailing level: rolling extreme of last twelve completed 5m candles
  plus/minus 2.5 x ATR14 5m. This is an initially **research-only rolling**
  trailing rule, not an irreversible stop since entry; unlike an exchange
  stop, it can move when the rolling window advances.
- Invalid/gapped, incomplete, or stale source bars -> FLAT. Never hallucinate
  missing candles, never use the current unfinished 5m bar.
- If a position is open and ER temporarily drops: HOLD unless the price
  invalidation fires. No new entry during a sideways regime.

## Benchmark / validation

'SMA 9/21 · 2m · Baseline SIM': simply sign of SMA9 minus SMA21 on completed
2m closes, one tranche, flat before reversal, without 5m direction, ATR or ER.

Both candidates appear in Strategilab v2's separate **Pris / trend (Tech100)**
family and route through 'strategy_lab_v2_replay.PURE_V3'.
Only PriceTrend #1 additionally has a guarded V3 LIVE closed-bar decision route;
the SMA-only baseline remains strictly SIM-only. Replays use next 1m open for execution; reversal cannot net cross in
one fill, and spread/fees are explicitly scenario-driven. Test matched periods
including the 2026-10-22 00:00–07:42 decline and sideways regimes. Report
net NAV, max drawdown, transactions, cost, first-entry lag, and time in
correct trend direction. No outperformance or real Saxo execution is claimed.

## Release gate

LIVE readiness in GitHub is **not** deployment or activation. PriceTrend V3
adapter and supported fixed-period config allow LIVE, but only on the exact
Tech100 `US Tech 100 NAS` / CfdOnIndex / Saxo UIC 4912 and at most
one Saxo-legal tranche. Existing V3 LIVE authority, broker product/account
ownership, precheck, budget/margin/cost limits, durable order guard, and
CLOSE -> Saxo-confirmed FLAT -> next OPEN are mandatory. Account config or
LIVE arming is never changed by this PR.

A new strategy/timeframe selection resets its decision context to broker
inventory and does not replay stale candles as a fresh opening. Gapped,
stale or malformed canonical 1m input fails closed for new entries.
PriceTrend ATR exit is a **rolling technical signal** rather than a
broker-native protective stop; any real-money rollout needs separate
verification of trade logs, exposure and contingency exits.
Deployment must match GitHub SHA and show correct worker/web health.
After release user must deliberately select and arm the intended bounded
account. No historical real-Saxo outperformance is claimed.

The selectable S timeframe also determines **decision frequency**:
1m responds to complete minute bars, 1h only to complete hour bars.
No partial candles, artificial quotes or adaptive timeframe in this version.
