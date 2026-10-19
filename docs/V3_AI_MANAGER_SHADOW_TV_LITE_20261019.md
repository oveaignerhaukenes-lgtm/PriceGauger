# V3 AI Manager SHADOW + TradingView Lightweight, 19 Oct 2026

## Current state
- Existing V3 per-instance price/MACD/Stochastic inspection (#761) now uses
  the canonical TradingView Lightweight Charts 5.2.1 component instead of
  a bespoke Plotly figure; three panes are visible and synchronized.
- Charts use exact instrument identity, fully completed 1m bars reaggregated
  to configured timeframe (no gap fill), timestamped execution markers
  for one Saxo account/instance and AI SHADOW markers.
- Price markers align to the relevant existing candle time, NOT verified
  Saxo fill prices. Original execution events remain accessible below chart.
- AI audit JSON records actual input and reasoning at evaluation time. No
  retrospective AI explanation is synthesized from deterministic trades.

## AI review worker
- Separate 30-second polling thread; no modification of 1-second V3 live
  worker, strategy or Saxo submit/reconcile path.
- Only enabled, LIVE-armed instances are candidates. Exact Saxo
  AccountId/UIC/AssetType netposition is checked with a GET, then
  CalculationReliability-verified open P/L is used. Missing/unreliable P/L
  does not trigger a model review.
- Default trigger after 60 seconds continuously negative. Slider 15–180
  seconds per instance under the inspection panel; individual SHADOW toggle.
  P/L returning nonnegative, account/position/strategy/timeframe changes
  or a monitoring gap over 90 seconds resets the loss episode.
- At most one model evaluation each 180 seconds per instance and four per
  rolling hour. Model calls require OPENAI_API_KEY; no fake placeholder AI
  results or unaccounted retries.
- Completed strategy timeframe OHLC, MACD and Stochastic and latest 1m
  close returns feed the existing strict-JSON paper technical model.
  Five-minute Saxo account value telemetry joins with its timestamp and
  CalculationReliability when available; exact account and broker identities
  are not part of model input. The broker open P/L is a separate read
  recorded at evaluation time. Results may advise HOLD, REDUCE, FLAT,
  REVERSE but never send a Saxo order.
- SHADOW decisions are append-only, account/instance/instrument scoped
  with model ID, as-of, timestamp, evidence hash and rationale. No
  broker mutation by this manager.

## Limitations and follow-up
- Currently canonical 1m OHLC is the fastest verified historical TA stream.
  There is no claim that 10/30-second market impulse is measured.
- Negative P/L may include spread; AI should interpret it with observed
  momentum rather than automatically closing positions. A model review
  is not a guaranteed emergency loss-stop deadline.
- Do not use SHADOW suggestions as LIVE instructions until controlled
  after-cost evaluation against static baseline on matched windows.
- A subsequent step can add after-cost realized attribution and delayed
  outcome labels for each AI decision, and evaluate whether AI actually
  improves return/drawdown/turnover.
