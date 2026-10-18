# Research-only missing history retry backoff (2026-10-18)

Context: Railway stream production logs regularly report "no canonical history
for Natural Gas" across MACD dry-run, Fast15, MTF shadow and "lacks canonical
warmup" for Cocktail Mode #1. Each research-only loop repeats DB history
reads every 30–60 seconds, raises and emits full exception tracebacks.
Market collection/subscription and Saxo risk/order paths must NOT pause.

## Change
- \`research_shadow_history_retry_v1.py\` is a standard-library-only
  120-second, in-process **negative-result retry** keyed by strategy, DB path
  and exact market/instrument ID.
- ONLY two exact \`ValueError\` forms trigger the retry:
  "no canonical history for <market>" and
  "Cocktail Mode #1 lacks canonical warmup for <market>".
- First unavailable read remains visible as WARNING. Subsequent scheduled
  cycles skip only that research evaluator, not the whole market or other
  strategies; the shadow summary records \`skipped_missing_history\`.
- After max 120 seconds another real DB read is ALWAYS attempted. If
  successful, its cooldown is immediately cleared and normal research
  evaluation resumes, including state persistence and any missed candles.
  Other exceptions are never suppressed or negatively cached.
- A process restart also clears the cooldown. No changes to the DB schema,
  data writes or to actual Saxo market subscriptions/reconnections.
- No changes to LIVE V3, V2 LIVE execution, risk reactions, watchdog,
  order guard, reconciliation, or stops. No market hardcoded.

## Expected benefit, NOT measured savings
Four redundant Natural Gas evaluations every 30–60 seconds repeatedly
fail. With 120-second cooldown, missing-history calls fall to at most one
per strategy per two minutes, assuming each loop keeps running. Logging
also avoids many redundant tracebacks. This does not guarantee a
particular PostgreSQL CPU or Railway billing reduction.

## Limits and follow-up
- Research signals for an instrument becoming ready while it is inside
  cooldown may be observed up to 120 seconds later. This bounded latency
  is restricted to research-only shadow strategies.
- This does not solve the reason Natural Gas is missing canonical data or
  its Saxo rollover/subscription warning; that needs separate source
  diagnostics and may also affect research coverage. It never masks other
  errors and does not invent data.
- Compare new Railway stream/PostgreSQL CPU, DB call rate and logged missing
  warnings over like-for-like active-market windows before attributing
  savings. See issue #735 and earlier PR #737 duplicate bar write fix.
