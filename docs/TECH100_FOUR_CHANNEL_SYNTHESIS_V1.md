# TECH100 four-channel synthesis V1 — research boundary

**State: manual, read-only data adapter and PAPER prototype, not integrated with V3 runtime, account controls, Saxo order APIs or LIVE.** All predictions require real historical evaluation before using a position.

## Four independent selectable modules

1. `macro_regime`: Gold and Brent percentage returns, US2Y/US10Y/US30Y *yield changes in basis points*. Trained horizon-specific long-range estimate; not MACD disguised as macro.
2. `cross_market_impulse`: same instrument family but a separate short-horizon model, with explicit abnormal movement threshold and a short data freshness limit. Only if the external market moves **precede** the traded TECH100 move in tests.
3. `tech_news`: tech earnings, chips, AI infrastructure and Nasdaq-relevant developments. Topic detection routes stories; it does **not** infer bullish/bearish impact.
4. `macro_news`: inflation, yields, Fed, employment and other economy-wide developments. Separate from tech stories, with separate validation.

The caller can select any nonempty subset of the four channels, including each individually or all four. Selected channels must have the **same forecast horizon**, verified input times, validated historical predictive evidence and a current signal. The default is to **abstain (FLAT)** if any selected module is missing, late or unvalidated. Offsetting channel signals are combined as a weighted *mean*, never added into arbitrarily larger leverage. Contributions remain visible individually. Initial reliability weights are a research hypothesis, not calibrated probabilities.

## Two independent destinations

- **Existing technical strategy — contextual entry gate.** Technical strategy retains its price/indicator timing, exits, ownership and order workflow. Synthesis can veto a **new** entry or reversal, never block exits, introduce extra entries or bypass normal V3 order reconciliation. Hold is not changed merely because external news flips.
- **Dedicated impulse instance — isolated PAPER intent.** A short-lived proposal with deterministic ID, direction, expiry and maximum research holding time. A future broker adapter must be a **normal V3 instance** on its own explicit Saxo account, respecting account owner, SMS, margin, budget, pending/unknown order locks, exposure and no-blind-retry rules. No direct OpenAPI submissions or automatic instance creation in V1.

The same source change can feed context and impulse research, but their *actual performance* must be compared independently. Opposite-side positions across accounts may reduce instantaneous directional exposure, while adding total spread, margin/funding requirements, operational risk and possible conflicting closes. Aggregate account exposure must be bounded before LIVE.

## Existing source reality and safe next gates

1. Existing `CrossMarketState` explicitly substitutes MISSING for US2Y/US10Y/US30Y when no verified intraday yield feed is configured. Do **not** reinterpret Treasury futures prices as yields. The official U.S. Treasury constant-maturity series is daily, not a seconds/minutes shock feed; verify licensed, actually received data and quote-age per instrument.
2. **Read-only canonical 1-minute Saxo bar adapter now exists:** manually select exact subscribed Tech100 UIC `4912`, Gold and Brent identities. Only completed, quality-flagged real-time, gap-free same-minute bars are eligible; this is **not** exchange-side delay certification. The manual UI displays actual lookback returns, not a predicted Tech100 return. Real **Gold/Brent quote latency/receipt quality** and historic yield availability must still be checked before a sub-minute lead claim. No interpolation.
3. **Read-only news/archive adapters now exist:** archived Telegram raw posts (where deployed) and optional legacy SQLite GDELT candidates are topic-routed into TECH/MACRO via the *later of* publication and actual recorded arrival. They are **not** signed, independently validated market-impact assessments and emit no trade signals. The GDELT SQLite file/table may not exist in production; the UI shows it unavailable, not an empty verified news feed. User-requested background AI OFF remains unchanged.
4. **Read-only CrossMarket snapshot lookup exists:** US2Y/US10Y/US30Y remain MISSING when no properly sourced data is present; even available 15-minute yield windows are explicitly marked `15M_ONLY` and are insufficient for the sub-minute impulse module. The adapter does not initialize the CrossMarket store or create a table.
5. Current cross-market ridge estimator uses chronological 70/30 holdout with purged training outcomes. Synthetic unit tests confirm its mathematical behavior but **do not establish market predictiveness**. Need multiple unseen time blocks, cost/latency-aware event return distributions, baseline comparison and conditional tests (growth vs inflation vs fear) before promoting any learned weight.
6. Evaluate 5m impulse and 60m+ regime separately; choose future horizons and thresholds based on recorded coverage and economic impact. A 0.04% quoted spread is small for a 1% move but material against a 0.1% move. Include observed spread, slippage and real completion latency in every PAPER comparison.

## Files and verified boundaries

- `tech100_four_channel_synthesis_v1.py`: selection, fresh signal checks, contribution/offset, no broker calls.
- `tech100_crossmarket_forecast_v1.py`: explainable five-market regression and shock detection, no data fetching.
- `tech100_news_channels_v1.py`: TECH and MACRO news topic separation and vetted signed-news aggregation; no model/API calls.
- `tech100_synthesis_routing_v1.py`: optional existing-strategy context gate vs dedicated impulse PAPER intent; no V3 authority.
- `tests/test_tech100_four_channel_synthesis_v1.py`: synthetic/no-lookahead/freshness/route safety checks.
- `tech100_synthesis_data_v1.py`: existing subscribed Saxo canonical bars, as-of CrossMarket state and received Telegram/GDELT archive candidates; only read calls.
- `pages/0_Tech100_Syntese.py`: manual selectable four-module data status, instrument picker, headline candidate inspection and **FLAT/INSUFFICIENT_EVIDENCE** outcome without forecast signals.
- `tests/test_tech100_synthesis_data_v1.py`: exact UIC, completion/quality, gap, delay/future, as-of snapshots, read-only archives and news boundary checks.

No production data was successfully inspected from this development container, no DB migrations, Railway deployment, Saxo REST/stream API request, account change or order was performed in this PR. Opening the manual research page against the actual deployed database is the next evidence check; then acquire real yield feeds, verify Gold/Brent delay status, train/replay and shadow the four channels. Only with later explicit approval could a guarded LIVE V3 integration be considered.
