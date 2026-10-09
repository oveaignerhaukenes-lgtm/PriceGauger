# AEN handoff — PriceGauger V3 live strategy cohort — 2026-10-09

## 0. Read this first

This is the current handoff from the Aen helper/evaluator thread after the October 8–9 LIVE strategy work.

Always refresh from fresh `main` before changing code.

**Runtime baseline before this documentation change:**  
`0e485affcf1167348216976b14d85001be07f60f` — **Treat V3 capital cap as a sticky capacity hold (#676)**.

At handoff time:
- GitHub had no open PRs.
- Railway production was green on worker, web, stream and Spring Trade Engine.
- V3 worker saw **4 enabled, owned, armed LIVE instances**.
- The user is actively running a small-money multi-account Tech100 comparison. Do not silently change strategy semantics or account bindings.

The highest-value principle from this round is:

> **Keep the base strategy autonomous. Higher layers should modulate or veto risk, not silently replace its direction logic.**

---

## 1. Product state from this thread

The project has moved from “can V3 execute safely?” to “can a mechanically robust strategy remain profitable across regimes, then be improved by bounded higher-level intelligence?”

The live experiment now has multiple Saxo subaccounts with roughly equal small balances. The user intentionally uses tiny development capital and wants to compare strategy behavior in real market conditions.

User-visible Saxo snapshot around 2026-10-09 08:56 CEST:
- Hvelvet: ~282.51 NOK
- Tech100-A: ~300.17 NOK
- Tech100-B: ~282.73 NOK
- Tech100-C: ~395.05 NOK
- Total: ~1,260.47 NOK

Do not use Saxo lifetime account percentages as strategy-return truth. If evaluating a strategy test, establish an explicit t0 account value and compare from that baseline.

Saxo margin is **global at client level**, not isolated by these subaccounts. Therefore PG per-instance capital allocation is essential: otherwise one strategy can consume the margin pool and starve the others.

---

## 2. Current LIVE runtime snapshot

Fresh worker evidence around 06:57–07:04 UTC on 2026-10-09 showed four enabled and armed instances:

- `b6008676-ec57-50e9-9cbf-3b0577c643ab`
- `f75cdc83-168b-5eb4-9224-ce73a058b6d3`
- `f115f072-036f-5e3b-a61e-459816070186`
- `f3e65462-77a4-5b0b-97a2-d744da0edc66`

Observed runtime state at that moment:
- `b600…`: R15/S2 regime strategy, actual ~+0.02, target ~+0.02. It attempted +0.03 and was correctly stopped by the 300 NOK cumulative PG cap because projected margin was ~444 NOK.
- `f75…`: R15/S2 regime strategy, built from flat to +0.01 and then +0.02; reconciled successfully.
- `f115…`: timeframe 5m, around flat in the latest cycles.
- `f3e…`: timeframe 10m, around flat in the latest cycles.

The logs prove timeframe/regime and armed state, but not all human account labels/strategy names in the same line. **Before touching bindings, read the current Fleet/config from production.** The user changes strategies from the UI during tests.

The user manually re-enabled Tech100-B shortly before this handoff. Treat that as intentional test setup, not an error to “correct”.

---

## 3. Strategy family added in this round

### Aen#2 — Sticky Regime

Commit:
`75f34631212997bb72d5111d2504a099c2421825` — PR #671

Catalog/UI:
**Aen#2 · Sticky Regime Rx/Sy**

Runtime:
`aen2-sticky-regime-v1`

Core behavior:
- R timeframe owns direction.
- S builds one tranche with regime.
- One adverse S slope = HOLD.
- REDUCE only after two adverse S slopes **and** weakening R.
- Confirmed opposite R regime forces FLAT before reversal.
- R near zero uses adaptive deadband and sticky HOLD.
- No new mutable strategy-memory DB; R/S history is reconstructed from canonical 1m bars.

Initial test result was strikingly good, but then exposed the main weakness: a fast, sustained opposite move could happen while R15 remained inside the adaptive deadband. The model could remain materially short through a broad bullish recovery.

This is not evidence that Aen#2 is bad. It identified the cost of its strongest property: sticky inertia.

### Aen#2.1 — Sticky Regime + Fast Exit

Commit:
`121ff0e8f6d451fa8333a394a2ffdce57c714f77` — PR #672

Catalog/UI:
**Aen#2.1 · Sticky Regime Rx/Sy · Fast Exit**

Runtime:
`aen21-sticky-fast-exit-v1`

Only intended behavioral difference from Aen#2:

- existing SHORT + **raw R spread > 0** => FLAT immediately
- existing LONG + **raw R spread < 0** => FLAT immediately
- adaptive deadband still gates new opposite entry/build

Conceptual rule:

> **Exit faster than re-entry.**

This fixes the specific Aen#2 failure mode where raw R crossed but the deadband still classified regime as neutral, causing HOLD of stale inventory.

Original Aen#2 was intentionally left unchanged as a control.

---

## 4. Important strategy lesson still open

The next problem is **pre-R-cross reversal handling**.

The user correctly observed a long, structured counter-move that should probably have triggered a defensive response before R15 formally crossed.

Recommended conceptual sequence:

```
ordinary counter-noise
    -> HOLD

persistent / accelerating countertrend
    -> stop building
    -> FLAT

countertrend keeps confirming
    -> optional one-tranche probe opposite

R confirms new regime
    -> build normally
```

Do **not** simply let S2 freely flip the whole strategy. That would destroy the sticky property and recreate high-turnover whipsaw.

The most promising architecture is to promote existing V3 modifier concepts:
- Impulse Detector
- Reversal Detector
- Whipsaw Detector
- Regime Detector
- Take Profit

At handoff, most of these exist in registry/UI concepts but are **not LIVE-wired**. `Reset on Loss` is the notable LIVE modifier.

The first useful promotion would be:
- **Reversal/Impulse may REDUCE or FLAT**
- they do **not** own full opposite-direction pyramiding
- optional “probe one tranche” can be a separate explicit policy later

This preserves base-strategy authority.

---

## 5. Margin architecture — critical fix completed

Saxo subaccounts share global client margin.

A bug was discovered in PG’s per-instance capital cap:

Before #673, the cap compared the Saxo precheck margin requirement for **the next order only**. Therefore a strategy could build 0.01 repeatedly:
- each +0.01 needed ~147 NOK margin
- cap was 300 NOK
- each individual step passed
- total position could grow far beyond the intended per-instance allocation

Meanwhile a strategy trying to open the same final amount in one order was blocked.

### #673 — cumulative V3 margin allocation

Commit:
`c82a8ada1b2f2759d49dbe1dca3e7d71518fb691`

Now ADD projects current per-unit broker initial margin across the **resulting same-side inventory**.

Example observed live:
- +0.01 ~148 NOK
- +0.02 ~296 NOK => allowed against 300 NOK cap
- attempted +0.03 ~444 NOK => blocked

This makes the user’s “~300 NOK per strategy” experiment meaningful even though Saxo margin is globally pooled.

The code deliberately does **not** force-reduce an already-existing oversized position after deploy. It stops further OPEN/ADD. Deployment itself must not unexpectedly trade.

### #676 — sticky capacity hold

Commit:
`0e485affcf1167348216976b14d85001be07f60f`

Capital saturation is now treated as an expected **MANAGING/capacity state**, not noisy repeated failure:
- capacity hold is durable
- scoped to strategy + timeframe context
- same-direction OPEN/ADD pauses at cap
- normal strategy decisions continue once capacity/context changes

Observed live on `b600…`:
- actual +0.02
- target attempted +0.03
- projected margin ~444 NOK
- cap 300 NOK
- runtime correctly entered “PG capital cap reached; holding LONG actual=0.02”.

---

## 6. Strategy/timeframe switch bug fixed

Previously, when the user changed strategy/timeframe, V3 could preserve the old closed-bar target/cursor and sit with stale inventory or stale target until a later bar.

Commit:
`4a844a43c0cd9db0c926b790b540ce101f8ae70c` — PR #675

Fix:
- context switch now aligns target with **current exact broker inventory**
- old strategy target is not inherited as a fresh intent
- tests cover broker-aligned strategy switches

This was important because one instance had tried to reopen a stale 0.10 target after a strategy switch.

---

## 7. TradingDesk execution markers fixed and simplified

Commit:
`ea6c6b61de3cf23d8562bedcc1647c06f04d87ba` — PR #674

The marker system had two problems:
1. current-candle executions could disappear at the right edge
2. one broken marker projection could blank the whole marker set

Current marker contract:
- one compact marker per durable V3 execution event
- account identity carried through marker projection
- active accounts receive distinct palette pairs
- **light shade = BUY/up**
- **dark shade = SELL/down**
- action is encoded mainly by marker size:
  - flip/reverse largest
  - open/add normal
  - reduce/close smallest
- no extra “F” text noise
- V3 marker projection is read-only from the web path
- V3, V2, manual and flat marker sources fail independently instead of blanking each other
- forming-candle/right-edge timestamps are included

Lightweight Charts has no native triangle-only marker primitive. The implementation uses compact `arrowUp` / `arrowDown` as the closest native shape.

If markers disappear again:
- first verify `autotrader_v3_execution_events` has the reconciled execution
- then inspect the source-isolated projection
- do not infer execution failure from missing chart UI

---

## 8. Higher-level PriceGauger architecture: direction from this thread

The repository already contains much of the intended intelligence stack:
- Technical Core v2
- canonical ContextSnapshotV2
- News Context / Telegram Flow
- Macro Calendar
- Holistic Composer
- TECH_ONLY vs TECH_CONTEXT benchmark/outcomes
- Spring Trade Engine research-only layer
- Forecast Learning / benchmarking

The recommended integration path is **not** to let these systems issue micro BUY/SELL orders directly.

Preferred flow:

```
Market data
    -> Aen#2/Aen#2.1 base strategy
    -> base target

Technical Core
Cross-market context
Macro Calendar
News / shock detection
Holistic Composer
    -> Policy Envelope

base target × Policy Envelope
    -> sizing / precheck / execution / reconciliation
```

A Policy Envelope should contain bounded modifiers such as:
- direction confidence
- max exposure
- build multiplier
- reduce sensitivity
- reversal threshold
- event-window state
- shock state
- valid-until
- provenance/fingerprint

Example:
```
base=Aen#2.1
regime=BULL
context=RISK_ELEVATED
event_window=NONE
max_exposure=75%
build_multiplier=0.5
hold_bias=1.2
valid_until=...
```

Key invariant:

> **Modulate, do not replace.**

If context/news/macro systems fail or become stale, the mechanical base strategy should still be able to run.

---

## 9. Forecast Learning / Learning Lab

The user regards the learning system as potentially one of PriceGauger’s most valuable future components, but does **not** want experimental telemetry to become execution-critical core.

Recommended boundary:

```
Core execution
    -> observed by Learning Lab
    -> hypotheses / counterfactuals / experiments
    -> evaluated
    -> explicit promotion back to Core
```

No live strategy should depend on Lab tables.

Useful eventual lab journal per decision:
- timestamp
- instance
- strategy/version
- R/S settings
- signal/regime state
- base target
- policy-modified target
- actual inventory
- action/reason
- execution link
- cost/P&L
- counterfactual “what base would have done”

The most important future learning question is not only “which strategy won?” but:

> **When a higher layer overrode/modulated the base strategy, did that intervention improve the counterfactual outcome?**

---

## 10. Current test philosophy

Do not judge Aen#2/Aen#2.1 from one clean trend.

A useful live sample should include:
- clean trend
- chop
- real regime reversal
- false reversal
- strong impulse + retracement
- news/event shock
- quiet low-vol period

The observed promising asymmetry is:

> easy to build with regime  
> harder to reduce against regime  
> fast exit when the regime genuinely invalidates the current side  
> conservative re-entry

Aen#2.1 is the current mechanical expression of that principle.

Do not tune it every hour based on the most recent chart. Let the live cohort produce evidence.

---

## 11. Immediate next priorities

1. **Read current Fleet/config before any mutation.** The user changes account/strategy settings interactively.
2. **Verify the four-account test remains armed and capital-capped.** Current runtime evidence showed all four armed.
3. **Do not change Aen#2 or Aen#2.1 while the live comparison is running unless the user explicitly asks.**
4. Build the next bounded strategy enhancement as a **modifier**, not by stuffing more logic into Aen#2.1.
5. First candidate: **Impulse/Reversal safety modifier** with authority to stop build / reduce / FLAT, not full unrestricted reversal.
6. Keep global Saxo margin visible in Fleet eventually. Distinguish:
   - PG per-instance allocated capital/cap
   - estimated/current instance margin use
   - Saxo global client margin available
7. Continue improving test telemetry so strategy outcomes can be compared from explicit t0 baselines.
8. When expanding intelligence, standardize one Policy Envelope contract around existing Composer/Context systems before creating new parallel subsystems.

---

## 12. Safety / authority invariants

Keep these intact:
- account cannot be simultaneously V2/V3-owned
- registry presence is not execution authority
- armed alone is insufficient; exact account ownership must match
- pending order identity is exact account + UIC + asset
- no blind retry after uncertain submission
- reconciliation is authoritative
- CLOSE/REDUCE must preserve exact broker truth
- strategy catalog identity and runtime identity remain separate
- context/AI layers do not directly bypass AutoTrader execution boundary
- user-visible LIVE off means authority off; it does **not** imply broker inventory is automatically closed unless explicitly designed/requested

For execution-sensitive work:
```
fresh main
-> inspect open PRs
-> inspect relevant code/tests
-> isolated branch
-> CI
-> fresh-main/mergeability check
-> guarded squash merge
-> verify exact Railway SHA
-> inspect runtime evidence
```

Do not use Railway “redeploy” if a fresh GitHub SHA is required; that can reuse an old build. Verify commit hash on the deployment.

---

## 13. Perspective / what matters most

The project is no longer blocked on basic order execution. The most useful development direction is now to preserve the simplicity of the mechanical core while adding **bounded, testable intelligence around it**.

Aen#2 was valuable because it finally produced a model that could make money by being intentionally reluctant to react to noise. Its failure mode was equally valuable: inertia can become dangerous during a genuine reversal.

Aen#2.1 fixed one precise error without destroying the original thesis.

The next architect should continue in that style:
- identify a concrete observed failure mode
- add the smallest mechanism that addresses it
- keep the previous model as a control
- compare live / replay outcomes
- only promote higher-level intelligence when it proves that it improves the base model’s counterfactual result

That is the shortest path from a collection of indicators to a genuinely learning PriceGauger.
