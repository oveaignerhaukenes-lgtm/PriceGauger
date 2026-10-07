# V3 strategy/settings runtime audit — 2026-10-07

Scope: canonical V3 catalog -> config -> closed-bar decision -> modifiers/control mode -> execution policy -> Saxo.

## Runtime strategy matrix

| Catalog key | Runtime key | LIVE ready | Audit |
|---|---|---:|---|
| macd | macd-trailing-v1 | yes | Closed-bar MACD regime + impulse logic is wired; fixed timeframe selection is consumed. |
| macd-stoch-v1 | macd-stoch-v1 | yes | MACD target plus Stochastic rollover FLAT authority is wired. Stoch 14/3 is strategy design, not instance-configurable. |
| macd-histogram | macd-histogram-v1 | yes | Histogram slope drives one target step per new closed bar. |
| price-macd | — | no | Catalog/UI only; must not be armed LIVE. |
| price-stoch | — | no | Catalog/UI only; must not be armed LIVE. |
| sfl | — | no | Catalog/UI only; must not be armed LIVE. |

## Confirmed settings wiring

- Fixed timeframe 1m/2m/5m/10m/15m/30m/1h is consumed by the LIVE bar reducer.
- Strategy selection resolves catalog identity to the registered runtime adapter.
- LIVE authority and exact V3 account ownership are enforced independently of config.
- OPEN/ADD passes through Saxo instrument-rule validation and one authoritative precheck.
- Reset-on-loss is the only catalog modifier currently instantiated in LIVE.

## Confirmed gaps before this audit tranche

1. `Adaptiv` is selectable but LIVE explicitly raises "not implemented".
2. Control-mode labels are persisted but LIVE constructs `TraderV3` with default `DETERMINISTIC`; Sim-Adapt/Overseer/God Mode are contract-only today.
3. All modifiers except `reset-on-loss` can be toggled/persisted but are not instantiated by LIVE.
4. Modifier settings persistence exists, but production LIVE does not load those settings.
5. Strategy closed-bar defaults use absolute `tranche=0.01`, `max_inventory=0.10`; this is Tech100-shaped rather than broker-instrument-shaped.
6. `TargetInventoryV3` uses a 0.01 canonical quantum. Products whose legal amount quantum is finer than 0.01 are therefore not safely general V3 targets.
7. Execution policy computes `budget_nok * exposure_pct`, but the current V3 sizing function deliberately does not enforce that value against broker capital impact. The slider therefore is not yet a true sizing cap.
8. REDUCE/CLOSE has a hard-coded 0.01 execution step in LIVE instead of using Saxo amount rules.
9. `MacdTrailingConfigV3.hard_reversal_ratio` is validated but not read by the decision function.

## Remediation rule

No UI setting may silently become a no-op in LIVE. Unsupported strategy/timeframe/control/modifier configuration must be visibly marked and fail closed before order evaluation. Legal order amount must come from Saxo instrument rules rather than a Tech100-specific 0.01 assumption. Capital policy must be broker-evidence-backed before being described as enforced.

