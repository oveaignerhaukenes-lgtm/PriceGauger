# ResponseDivergence v1

`ResponseDivergence` is a descriptive observation layer. It compares a directional information impulse with the later, temporally aligned market response. It does not explain causality and does not influence Decision State or forecasts.

## Inputs

- Persisted `InformationStateSnapshot.state_change`.
- Existing `ASSET_WEIGHTS` for the selected market; v1 introduces no new Silver weights.
- Persisted `CrossMarketStateSnapshot` observations and their explicit window coverage/reference timestamps.

## Temporal rule

A response window is evaluable only after it has matured. For example, a 15-minute response to Information State at `t0` must come from a later CrossMarket snapshot whose valid 15-minute reference points back to `t0` within the alignment tolerance. A trailing 15-minute return ending at `t0` is never treated as the response to information observed at `t0`.

## Outcomes

- `ALIGNED`: realized market direction agrees with the information-implied direction.
- `DIVERGENT`: realized market direction is opposite the information-implied direction.
- `UNCONFIRMED`: the realized response remains inside the small response dead zone.

Neutral information impulses, invalid CrossMarket windows, and temporally misaligned observations are not persisted as divergence evaluations.

Supporting Gold, Brent, DXY, and Treasury observations are stored as descriptive context only. v1 does not label any supporting move as a cause or transmission channel.

## Scope guardrails

- No `TransmissionState`.
- No causal classification.
- No new directional weights.
- No Decision State or forecast influence.
- No notifications or trading actions.
- No new market-data production path.
