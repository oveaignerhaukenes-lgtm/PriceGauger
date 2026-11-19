# TECH100 four-channel synthesis V1 — research boundary

**State: source-only PAPER prototype, not integrated with V3 runtime, account controls, Saxo or LIVE.** All predictions require real historical evaluation before using a position.

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
2. PriceGauger has canonical 1-minute subscribed Saxo bars and an event-driven Tech100 BBO recorder; real **Gold/Brent tick receipt quality** and historic yield availability must be checked before a sub-minute model can claim a lead. Do not interpolate absent instruments or permit late-arriving news to leak into earlier decisions.
3. News input consists of pre-classified `AssessedNewsItem` records with distinct received/published times. Integration with existing GDELT/Telegram/news stores and a directional impact scorer **is not yet implemented**. Keyword routing alone emits no trade signal. User-requested background AI OFF remains unchanged; future AI scoring must be a separately approved opt-in/manual action.
4. Current cross-market ridge estimator uses chronological 70/30 holdout with purged training outcomes. Synthetic unit tests confirm its mathematical behavior but **do not establish market predictiveness**. Need multiple unseen time blocks, cost/latency-aware event return distributions, baseline comparison and conditional tests (growth vs inflation vs fear) before promoting any learned weight.
5. Evaluate 5m impulse and 60m+ regime separately; choose future horizons and thresholds based on recorded coverage and economic impact. A 0.04% quoted spread is small for a 1% move but material against a 0.1% move. Include observed spread, slippage and real completion latency in every PAPER comparison.

## Files and verified boundaries

- `tech100_four_channel_synthesis_v1.py`: selection, fresh signal checks, contribution/offset, no broker calls.
- `tech100_crossmarket_forecast_v1.py`: explainable five-market regression and shock detection, no data fetching.
- `tech100_news_channels_v1.py`: TECH and MACRO news topic separation and vetted signed-news aggregation; no model/API calls.
- `tech100_synthesis_routing_v1.py`: optional existing-strategy context gate vs dedicated impulse PAPER intent; no V3 authority.
- `tests/test_tech100_four_channel_synthesis_v1.py`: synthetic/no-lookahead/freshness/route safety checks.

No production data read, DB migrations, Streamlit route, Railway deployment, Saxo API request, live account switch or order in this PR. Next implementation increment: verified exact-source data adapters and a manual synthesis research page with separate channel outcomes; after that replay and shadow controls, and only with later explicit approval a guarded LIVE V3 integration.
