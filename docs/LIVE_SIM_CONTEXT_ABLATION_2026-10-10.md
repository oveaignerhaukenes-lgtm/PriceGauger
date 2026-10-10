# Live-Sim Context Lab — five frozen candidates × paired macro and geopolitical AI overlays

## Purpose and causal contract

This is a bounded **forward-only, PAPER-only** causal experiment. It does not alter V2/V3 LIVE engines, account ownership, leverage, capital caps, strategy selectors or broker positions. It reuses the already AI-produced Context v2 / News Context assessments and the existing official macro calendar. **No new per-bar LLM calls** and no geopolitical buy/sell prediction are added.

Selection locks the five top scoring *qualified* existing LAB-native strategies once, after at least 120 fresh 1m-bars and the existing RECENT scorer's >=25 5m snapshots and >=2 paper trades. All results begin only *after* cohort selection; the selected cohort never rotates based on study outcomes.

Each selected strategy has four equal-start virtual risk-overlay ledgers:
- BASE: unmodified target, matched control.
- MACRO: hold flat around *already observed* scheduled US macro releases (15 minutes before, 20 after). No directional claims about release surprise.
- GEO: halve target exposure only when the earlier published Context v2, backed by AI-classified Telegram/News evidence, confirms elevated global geopolitical stress.
- BOTH: apply both. All fills occur at the **next minute's open**, never at the bar whose close triggered a context decision.

All four arms pay the same 5 bps per unit of exposure change. They start at virtual 10,000 NAV only when forward collection begins. Sidecars reuse an existing parent strategy's closed-bar target; this does not enlarge the 100 ACTIVE research-strategy cap or create any broker orders. Repeated bars are idempotent.

## Inputs and provenance

**Macro:** once every 12h, the independent lab worker consults existing `macro_calendar.load_macro_calendar` for future CPI, PPI, NFP, PCE, GDP and FOMC calendar events. Persist `seen_at` when the lab actually obtained the schedule. Only events with `seen_at <= decision_bar` can influence a paper decision. No historical retrofit.

**Geo:** existing `context_v2_snapshots` rows with `scope_key='global'`; require `as_of`, `recorded_at`, all source `published_at`/`observed_at` and `coverage_end` not after the decision bar. Require `FRESH`, freshness <=15 minutes and confidence >=0.6 plus adequate confirmation-quality score. A global risk score is not necessarily NASDAQ-specific and must be labelled as a proxy in interpretation.

**Missing or stale evidence:** never assume a favorable direction or synthesize a score. Apply no contextual adjustment; explicitly record source data coverage (%) and real trigger bar counts for each candidate/arm. A sidecar with no triggers cannot be counted as an improvement due to context.

## Evaluation

The Live-Sim Lab panel displays per-parent/per-arm forward NAV, percentage-point advantage over matched BASE, drawdown, turnover/trades, market sample size, macro data coverage, geo coverage and activated windows. The analysis is paired **within the same selected parent and same subsequent minutes**; do not compare different starting periods.

The initial study is a **risk-filter ablation**. It tests whether these inputs would help avoid uncertain conditions, not whether an LLM can reliably forecast an index direction. With few events, high correlations, or insufficient context coverage, classify results as inconclusive. Measure trading costs, missed profitable breakouts, signal delay, bad short/long windows, and out-of-sample performance over multiple sessions. *A negative Friday cannot be retroactively re-scored with Saturday's geopolitical news.*

## Known limitations

- Existing News Context / Context v2 semantic evidence is AI-generated externally; freshness, confidence and labeling quality may be poor. No extra context reports are fabricated in the Lab.
- Macro calendar supplies **scheduled publication times**, not actual economic surprises, revisions, forecasts or yields data; separate economic-indicator evidence is future work.
- LAB-native prototypes are not the same as live Aen#2/2.1; this study does not by itself demonstrate LIVE profitability.
- A higher-context layer that autonomously proposes strategies is still isolated from live money; automatic modification of LIVE strategy policy requires independent review and explicit authorization.
