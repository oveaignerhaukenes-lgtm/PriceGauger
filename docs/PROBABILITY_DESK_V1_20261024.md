# Probability Desk v1 — PriceGauger probability-first research (2026-10-24)

**STATUS: RESEARCH DESIGN ONLY. ISOLATED BRANCH. No executable strategy, no Saxo orders, no UI route, no schema migration, no LIVE arming or account change.**

## Decision and objective

Investigate a shift from trigger/indicator-first intraday trading to **calibrated conditional outcome distributions** and low-frequency, risk-bounded position management. Target US Tech 100 NAS and **US 500 (Saxo `US500.I`)** index CFDs. Research horizons: **next US regular-session close (1D)** and **five US trading-session closes (5D)**. Define and label each forecast target unambiguously (not ambiguously "tomorrow": handle weekends, holidays, daylight-saving and extended index-CFD sessions separately).

Question at every forecast cut-off: *Given information genuinely public and available at timestamp t, what is the conditional distribution of the next H-session gross return and net realizable P/L after costs, and what exposure, if any, is warranted?*

Do not optimize for percentage of winning trades, directional hit-rate alone, or number of trades. Primary outcomes: **net reconciled account P/L and return adjusted for drawdown/tail risk**, with forecast calibration and correct capital allocation. "FLAT" is a legitimate forecast-driven action.

## Fundamental correction: odds are not edge

`P(return > 0)=0.62` alone does not imply a long: a 62% chance of a small gain can lose money when the remaining 38% implies a much larger loss. Likewise an increase in upward probability can occur after a price rally has already consumed the upside. Size from **net expected payoff, tail losses and forecast uncertainty relative to live entry price**, never probability alone. Reject forecast changes that do not exceed execution/funding cost or model-confidence thresholds. Nasdaq 100 and S&P 500 exposures are correlated and must share a portfolio risk budget.

Raw price history is not avoidable in statistical estimation; the conceptual change is that moving-average/MACD/Stoch crossovers cease to be **entry authority**. Lagged observations, volatility, return distribution and market microstructure may still be admissible predictors when evaluated prospectively. Probabilities from purely historical data can still be misleading when regime shifts or breaking news dominate.

## Phase A — Instrument viability, before trading (read-only once Saxo OAuth recovers)

1. Search account-entitled Saxo `CfdOnIndex` for `US500.I`; record exact UIC, AssetType, trading currency, account eligibility, `IsTradable`, sessions and data-feed entitlement; never hardcode a guessed UIC.
2. Query `/ref/v1/instruments/details/{Uic}/{AssetType}` for account-specific `MinimumTradeSize`, `AmountDecimals`, `IncrementSize`, `ContractSize`, `PriceToContractFactor`, `MinimumOrderValue`, `TradableOn` and order constraints. Verify **0.01 contract on this specific LIVE account**; Saxo advertises fractions "as low as 0.01" for *most* index CFDs, not a guarantee for this UIC/account.
3. Read indicative bid/ask, currency conversion, market data delay/quality, financing long and short, account-specific initial/maintenance margin and Saxo cost illustration. Calculate **NOK exposure, margin, 1% underlying move P/L, overnight funding and round-trip cost for exactly the smallest permitted increment**. Record SOURCE, TIME and VERIFIED/MISSING for each.
4. Compare US500 against US Tech 100 NAS on **minimum useful trade size and NOK loss per realistic overnight gap**, not merely price levels or common nominal 5% initial-margin advertisement.
5. Block all order execution; use the existing Strategilab v2 cost/read-only interface where applicable. During OAuth outage, instrument feasibility remains **unverified**.

Saxo sources:
- https://www.home.saxo/products/cfds (index CFD fractional amounts, account conditions)
- https://www.home.saxo/nb-no/products/margin-information (US 500 / US Tech 100 listed initial margin 5% under normal conditions)
- https://developer.saxobank.com/openapi/referencedocs/ref/v1/instruments/get__ref__details_uic_assettype
- https://www.home.saxo/rates-and-conditions/cfds/spreads-and-commissions (overnight funding)

## Phase B — Data contracts (as-of, auditable)

- Market observations: exact Saxo UIC/AssetType, completed OHLC bid/ask when available, genuine quote timestamps, regular-session close and previous close, realized 1D/5D returns, overnight gaps, market holidays. Keep data-source and delayed-price flags; reject gap-filled invented "trades". Reuse `pg_v2_market_bars_1m` when continuity and UIC match; aggregate to sessions with exchange calendar. Saxo Chart v3 `Horizon=1440`/`10080` supplies daily/weekly chart samples, but first inspect historical coverage and data licensing; it is not a substitute for actual bid/ask execution prices.
- Macro/events: as-of release *time*, **actual-vs-consensus surprise** if consensus was publicly known before event, category (CPI, PCE, NFP, FOMC, rates/yields, major corporate earnings, geopolitical/shocks), provenance, revision timestamp and confidence. Do not treat an event already priced in as new edge. Scheduled pre-event expectation and published post-event surprise are different fields.
- News extraction may use LLM **only to structure observed facts, entities, novelty and source reliability**; it must not invent numeric probabilities or access future headlines. Store extracted fact, cited source, retrieval/published times, model/extractor version and corrections.
- Position/account: current reconciled broker position, account equity, margin, live costs, related-market portfolio exposure; never replace known Saxo position with internally inferred fill.
- Append-only research observations: `snapshot_time_utc`, `data_cutoff_utc`, `instrument_uic`, `source`, `feature_version`, `model_version`, `forecast_horizon`, `forecast_distribution`, `calibration_version`, `cost_assumptions`, `decision`, `reason`, `quality_flags`, later realized outcome. Use separate PAPER state, no writes to LIVE ownership/arming tables.

## Phase C — Baselines before complexity

1. **Base rate**: unconditional empirical 1D/5D return distribution, including downside tail, volatility and long/short outcomes; adjusted for historical era and sampling uncertainty.
2. **Conditional history**: shrinkage/hierarchical distribution by observable market conditions: recent signed return, volatility/range, overnight gap, position within current 5D move, previous close vs open, calendar/session and known macro regime. All measured as of decision time. No MACD-cross trigger.
3. **News/event update**: add only archived and timestamped actual surprises and genuine source updates; compare to the price-only model. Model event impact conditional on whether the fact is scheduled, surprise and already incorporated in prices; avoid multiplying correlated evidence as though independent.
4. Begin with transparent empirical frequencies / regularized logistic direction model + separately estimated gain/loss magnitude and tail model; complexity later only if walk-forward evaluation warrants it. Produce forecasts for LONG/SHORT/FLAT rather than only a bullish score.
5. Posterior/conditional forecast revises on new qualifying information. Never label an uncalibrated LLM narrative numeric "75% chance" without historical calibration.

A forecast row reports:
- `P(R_H > 0)`, `P(R_H < 0)`, `P(R_H > cost+target)`, `P(R_H < -loss_threshold)` and 5th/50th/95th percentile returns;
- expected long and short **net** returns including bid/ask, commissions, FX and multi-night financing;
- downside quantile / expected shortfall, uncertainty/coverage (sample count, effective sample size, OOD/regime-shift markers), last update and the observations that materially changed probabilities;
- position action recommendation and **why doing nothing may be superior**.

The 1D and 5D forecasts must be estimated and calibrated separately. Overlapping 5D labels in backtests are dependent, so use embargo/blocking appropriate to the forecast horizon.

## Phase D — Forecast-to-position management (PAPER only)

Define forecast-based *target exposure* on bounded **portfolio/account equity risk**, not leverage scaled linearly with `P(up)`.

- **Enter** only when modeled net expected long/short edge exceeds both a meaningful confidence buffer and full cost estimate.
- **Increase** one permitted Saxo increment only if **incremental** expected net value at current price remains favorable, credible lower bound supports the action, margin/free collateral supports it and worst-case gap/tail loss remains within risk limits. Probability rising alone does not increase size.
- **Reduce** when remaining edge shrinks, tail risk rises, event assumptions reverse or shared Tech100/US500 risk budget is consumed. Avoid churn through persistence/hysteresis/cooldown; exit thresholds may differ from entry thresholds.
- **Flat/reverse** when net edge disappears or portfolio guard is hit. On any later LIVE candidate preserve existing guarded CLOSE -> confirmed broker FLAT -> separate OPEN. No atomic flips, no invented fills, no automatic arming.
- **Force intervention** under stale market feed, missing evidence, severe unmatched broker exposure, upcoming known high-volatility binary event as specified by policy, or account margin danger. If Saxo API is unavailable, no automatic close is possible: report **BROKER_DISCONNECTED**, do not falsely mark positions flat.
- Use an explicit per-account exposure cap, maximum portfolio risk across correlated index CFDs, maximum tail-loss budget, collateral buffer, total drawdown halt and event-gap buffer. Quantify safeguards from actual contract size and account equity, not hardcoded percentages without justification.
- Exit rules, take profit and stop protection can remain as mechanical **risk safeguards**; they do not supply entry probabilities. Separate forecast invalidation from capital-preservation triggers.

## Phase E — Evaluating whether any edge exists

- Evaluate true **walk-forward** windows, historical as-of vintages, purge and embargo overlapping 5D labels, explicit retraining schedule, realistic transaction/financing/FX/roll costs, and broker-instrument session/gap risk. Compare against always-flat, unconditional directional prior, buy-and-hold exposure at matched risk, and existing rule-based strategy at matched account risk.
- Forecast metrics: Brier score, log loss, reliability plots/calibration by bucket, directional accuracy with base-rate comparator; distribution coverage/quantile loss; net realized opportunity expectancy by model-decile.
- Economic metrics: net NOK P/L per unit equity, drawdown, tail loss, turnover, exposure utilization, funding, hit rate *and* average win/loss, account-Saxo reconciled realized P/L (later, separately) and behavior in adverse regimes.
- **Proof threshold**: require positive risk-adjusted net advantage in multiple forward out-of-sample windows with uncertainty bounds versus simple baselines; otherwise no LIVE deployment. More data or more AI narrative is not proof of an edge.
- Do not optimize on the evaluation interval, conflate matched simulated PAPER fills with realized broker fills, or use market-news hindsight. Shadow forecasts should continue and be scored even when no position is taken.

## Proposed implementation modules (not yet created)

1. `probability_desk/markets.py`: exact instrument registry and read-only Saxo capability check.
2. `probability_desk/datasets.py`: session bars, as-of features, event vintages, quality gates.
3. `probability_desk/forecast.py`: transparent baseline, 1D/5D return distribution and calibration.
4. `probability_desk/position_policy.py`: PURE target-position function with account/portfolio risk, fees, funding, no broker calls.
5. `probability_desk/replay.py`: independent as-of event-driven PAPER replay reusing Strategilab v2's exact-UIC data/cost discipline.
6. `pages/0_Probability_Desk.py`: research-only read model, 1D/5D probability distribution, explanation of updates, news timeline, current PAPER position, risk/cost and model-quality status.
7. `tests/test_probability_desk_*.py`: unit tests of no look-ahead, historical publication/revision times, regime and holidays, trading size constraints, direction-vs-EV conflicts, correlation caps, data gaps, model uncertainty, multi-day funding, stale/broker-down lockout.

## Research milestones / stop gates

- **M0 — Instrument**: broker-auth recovery, read-only US500 instrument economics, exact fractional increment and account eligibility. Until then indicate *not verified*.
- **M1 — Price-only forecasts**: independent 1D and 5D probabilistic baselines on historical Tech100/US500, tests and proper forward metrics; static PAPER dashboard. No news/AI in this first comparison to avoid confounding effects.
- **M2 — News and adaptive odds**: timestamped event surprise ingestion, measured incremental calibration/EV benefit versus M1, no subjective probability multiplication.
- **M3 — Position policy PAPER**: position changes with costs, margin, combined index exposure and rare-day gap risk; report turnover and net return against flat/simple baselines.
- **M4 — Shadow then optional bounded LIVE**: only after demonstrated out-of-sample net edge, reliable Saxo OAuth, exact broker reconciliation, explicit user authorization and separate LIVE safety review.

**Operational rule:** existing PriceGauger V3 LIVE and Strategy Lab v2 continue untouched. Never merge/enable an execution adapter, switch a strategy, arm an account, or submit a Saxo order as a side effect of a research PR.
