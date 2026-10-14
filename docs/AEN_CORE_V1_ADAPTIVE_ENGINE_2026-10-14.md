# AEn Core v1 — Adaptive Engine contract (SIM-first)
Date: 2026-10-14. Status: implementation blueprint, NOT enabled in runtime.

## Scope and invariants
AEn combines deterministic MACD/structure/position sizing and a bounded adaptive timeframe controller. Existing V3 LIVE fleets, Saxo accounts, V2 reference, Legacy experiments, and historical data are unchanged. First release is read-only replay / PAPER only. Any live rollout needs its own explicit authorization and proven reconciliation parity.

AEn has THREE separate clocks:
1. `signal_tf_minutes`: closed-bar MACD time resolution, allowed [1,2,5,10,15,30].
2. `structure_tf_minutes`: chosen candle resolution for swings; explicit independently configurable parameter per market (defaults to signal timeframe).
3. `execution_clock`: timestamp when an actionable event is known (closed bar + swing confirmation), with fills at next eligible market quote/bar, never retrospectively at signal close.

The AI/controller may modify ONLY `signal_tf_minutes` in the first controlled version. It cannot choose position, side, leverage, stop, strategy family, structure parameters, risk cap, market or account. All controller decisions are audited with input timestamps, eligible candidate frames and reasons. Default controller is MANUAL; initial AUTO controller is deterministic and can be compared to an AI policy in PAPER.

## Deterministic market structure
- Use *confirmed* pivot highs/lows over user-defined left/right completed bars. A swing at T is only available when the right-side confirming bars have closed; never backdate actionable orders.
- HH: latest confirmed pivot high > preceding confirmed pivot high (with configurable minimum separation/tick tolerance). HL: latest confirmed pivot low > previous confirmed pivot low. LL and LH symmetric.
- A rising candle crossing the previous high does not by itself confirm a pivot or authorize ADD.
- A downtrend's LL/LH confirmation must be mirrored, not inferred from sign-flipping long code.
- Configurations are market-specific; instrument tick size, 0.01-lot quantity precision, trading sessions, volatility and available volume data are validated.
- Account for gaps/closed markets, irregular/missing bars and zero-volume/indicative volumes. Missing data => block ADD and opening; allow protective reductions after safe broker confirmation.

## Position state machine
State = FLAT/HOLD, LONG(n), SHORT(n), n integral, 0 <= n <= max_units. Each Tech100 unit = 0.01 lot (do not assume for other markets).
- With an established uptrend, start LONG(1) on authorized entry. On a newly confirmed HL following HH, permit +1 once per unique structure event, capped at max_units; no duplicate scaling on repeated ticks.
- On structural break below protected HL: configurable reduce tranche(s), never add against weakened trend. On confirmed LH after break: target FLAT/HOLD, not simultaneous short. Downtrend symmetric.
- From HOLD, HH then confirmed HL authorizes LONG(1); LL then confirmed LH authorizes SHORT(1). An impulse may trigger defensive FLAT earlier, but NOT an unconfirmed opposite entry by default.
- A direct regime flip must execute CLOSE -> observed verified FLAT -> OPEN minimal 0.01 in the opposite direction; NEVER send direct netting shortcut around v3 durable intent and Saxo reconciliation.
- Oscillatory flips at 1 unit are permissible ONLY after separately confirmed signals; cooldown/risk gates limit serial churn. Controller timeframe switches alone never trade.
- Max-unit arrow UI changes hard ceiling, not target inventory. When cap lowered below observed quantity, reduce-only on next safe reconciled cycle. No automatic promotion of cap from profitable backtests.
- Safety: broker-confirmed position is authoritative, account ownership exclusive, pending order freezes conflicting decisions, session/market-closed checks, margin/exposure NOK controls, order throttles and loss controls remain enforced.

## Impulse Detector (OFF by default)
Detect against-position displacement as normalized closed-candle return or ATR-based move; user-visible configurable threshold. Optional *reliable* volume acceleration gate compares like-for-like session bars.
- Against position + strong valid volume => immediate *next executable opportunity* protective reduction/FLAT, never fill inside an already closed candle.
- Against position, weak/missing volume => configurable retrace wait with hard time/price loss boundary; missing volume never silently treated as strong confirmation.
- With-position impulse => may preserve existing exposure, never exit by default.
- No repeated impulse execution for same bar, no order if reconciliation unresolved.
- Separate research toggle and parameter display in SIM; effect scored net of all turnover.

## Adaptive controller: layered timing
- Slow timeframe (e.g. 10m) keeps broad regime; 5m/2m monitor regime decay; 1m impulse can warn early.
- Change `signal_tf_minutes` only at completed bars, dwell/cooldown and hysteresis constraints. Cooling alone does not prove reversal. A change may change future eligibility but NEVER directly cause a broker order.
- 1m bearish pulse => candidate probe SHORT(1) only when previous LONG is safely flat and deterministic entry criteria pass. 2m confirmation permits +1; 5m confirmation and appropriate LL/LH structure permit further scaling, within cap.
- Model both trend-continuation and strong-reversal scenarios explicitly; do not mix MACD histogram weakening with an actual bearish cross.
- Avoid historical cherry-picking: controller decisions use only data actually available then; walk-forward/out-of-sample evaluation per market.

## UI
Live-Sim Lab > Core Strategies, separate from V2 Strategies and Legacy Strategies.
Per row: strategy name, market, SIM/LIVE status, timeframe with MANUAL/AUTO control, LONG/SHORT/HOLD, actual/allowed integer units with +/- arrows, turnover, estimated net P/L and cost toggle, active Structure Scaling and Impulse Detector toggles. Expand for timeframe of HH/HL, pivot confirmation bars, momentum and volume thresholds, strategy audit/explanations.
Chart markers show trade delta and total exposure; distinguish virtual SIM orders vs actual LIVE fills. Update replay after all parameter changes. No UI toggle may silently authorize LIVE.
Four variants to compare: MACD Hold, MACD Histogram, Hysteresis, MACD+Stochastic. Baselines include unmodified NextGen and V2 MACD Flip reference.

## Test/acceptance gates
1. Closed-bar and swing causality with golden vectors (including missing/gapped timestamps, pivot confirmation delay).
2. LONG/SHORT symmetry, HH-HL and LL-LH event deduplication, HOLD transition, cap 1/minimal flip, cap decrease reduce-only.
3. Timeframe transitions cannot create immediate trades or duplicate events. Controller cannot touch risk or Saxo execution.
4. Impulse with/against position, valid/missing volume and retrace timeout/loss boundary.
5. Same history, next-bar fills, costs ON/OFF; compare gross/net, spread, commissions, financing if known, counts of <1/2/5m reversals, drawdown and regime-conditioned results.
6. Immutable decisions and replay reproducibility: dataset version, parameter hash, rule version, controller reason, session and traded quantity.
7. LIVE readiness demands existing V3 exact-account safety chain, partial-fill/pending-order replay, Saxo minimum size per instrument, market downtime, CI, deployment health and explicit separate user approval.
8. DB efficiency: bounded retention and sampled aggregates, no additional unbounded raw quote ingestion while Postgres growth is unresolved. No DB deletion or migration for this spec.

## Rollout order
A. Build deterministic pure engine and exhaustive unit tests, SIM only.
B. Wire to existing NextGen Live-Sim costs, selectors, chart/exposure UI.
C. Benchmark four variants on identical causal 1m history and multiple regimes; expose lookahead/selection risk.
D. Add deterministic AUTO timeframe and compare against fixed 1/2/5/10/15m baselines.
E. AI timeframe proposals PAPER only; evaluate OOS and switch frequency before considering permission expansion.
F. Separate explicit LIVE proposal once meaningful net results, operational safety and Saxo fills are verified.

## Existing repo integration contracts
Read `docs/AEN_ARCHITECT_HANDOFF_2026-10-13.md`, `docs/V2_STRATEGIES_REFERENCE_PARITY_2026-10-13.md`, current NextGen SIM implementations and V3 durable order/reconciliation modules before coding. #706 added the V2 vs NextGen reference menu; reuse rather than replace it. NEVER re-enable the old V2 LIVE loop as part of AEn.
