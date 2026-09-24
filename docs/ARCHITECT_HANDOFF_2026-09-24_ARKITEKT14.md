# PriceGauger Architecture Handoff — Arkitekt 14 — 2026-09-24

This is the authoritative Arkitekt 13 → Arkitekt 14 handoff after the September 21–24 cleanup, chart isolation work, and creation of the AutoTrader V3 control plane.

Always refresh from current `main` before branching. Baseline at handoff creation: `8a905fd2a1c25294783ed266faa67a3fe0f6b480`.

## 1. Product direction: finish V3

The user explicitly prefers finishing **AutoTrader V3** rather than spending more effort extending the old V2 control surface. Keep V2 operational while migrating behavior with parity tests, but do not add new combinatorial V2 strategy variants unless required for a production repair.

Target V3 UX:
1. choose one **base strategy**
2. choose **timeframe** independently: 1m / 2m / 5m / 10m / 15m / 30m / 1h / **Adaptive**
3. toggle independent **modifiers**, each with a settings gear
4. choose control mode: **Manual / Sim-Adapt / Overseer / God Mode**
5. all paths converge on `TargetInventoryV3` → Risk Governor → hardened Execution → Saxo

Timeframe must not be encoded into strategy identity. Adaptive timeframe is a selector layer and can later consume Regime Detector output.

## 2. Work merged in this session

- PR #498 — TradingDesk V3 reduced to a minimal cockpit/status panel.
- PR #499 — dedicated top-level **AutoTrader V3** page + durable strategy/timeframe/modifier/control-mode configuration.
- PR #500 — persistent settings popovers for Impulse, Reversal, Take Profit, Whipsaw and Regime.
- PR #501 — contracts for Sim-Adapt, Overseer and God Mode.
- Earlier chart work: #491 restored forming candle source, #492 static fragment clock, #493 full-page refresh, #496 isolated Live Chart, #497 fixed Live Chart timestamp normalization.

Current main is newer than #501; refresh before work.

Important files:
- `pages/0_AutoTrader_V3.py`
- `autotrader_v3_registry_v1.py`
- `autotrader_v3_config_v1.py`
- `autotrader_v3_modifier_settings_v1.py`
- `autotrader_v3_sim_adapt_v1.py`
- `autotrader_v3_ai_modes_v1.py`
- `autotrader_v3_pipeline_v1.py`
- `autotrader_v3_live_runtime_v1.py`
- `autotrader_v3_closed_bar_driver_v1.py`
- `autotrader_v3_execution_plan_v1.py`
- `autotrader_v3_live_authority_v1.py`
- `tradingdesk_automanager_simple_v1.py`

## 3. Non-negotiable execution invariant

Strategy/AI owns desired exposure, never broker mutation.

`desired target → close conflicting exposure → confirm exact Saxo FLAT → open desired exposure`

Exact account + UIC + asset type is the authority boundary. Ambiguous broker state blocks mutation. Restart/UI/model reevaluation must never imply a close.

God Mode does **not** get a Saxo/order API. It may produce a direct target plus confidence/reason/expiry; that target still passes Risk Governor and the same execution engine.

The user does not want hidden safety arming layers between an explicit V3 LIVE ON toggle and actual management. If ON cannot manage, UI must say so clearly. Safety belongs in invariant/risk/execution correctness, not in surprise inactivity.

## 4. Immediate technical gap: V3 control plane is not yet the V3 runtime

This is the next critical task.

The dedicated V3 page persists the new configuration, but `autotrader_v3_live_runtime_v1.py` is still hard-wired:
- enrollment filtering uses a single imported `STRATEGY_KEY_V3`
- closed bars are hard-coded to 5m
- the closed-bar driver is effectively MACD-Histogram-specific
- selected V3 base strategy/timeframe/modifiers/control mode are not dispatched by the LIVE runtime

Do **not** merely swap another global strategy constant. Build proper dispatch.

Recommended contracts:
- `StrategyRegistryV3`: observation/context → base target
- `TimeframeSelectorV3`: fixed or Adaptive → selected timeframe + reason
- `ModifierRegistryV3`: ordered pure target transforms
- `Recipe/ConfigV3`: base strategy + timeframe policy + ordered modifier settings
- `ControlModeV3`: Manual / Sim-Adapt / Overseer / God Mode
- then existing Risk → TargetInventory → Execution

Modifier ordering must be explicit and audited.

## 5. Modifier architecture

Keep conceptual boundaries clean:
- **Impulse Detector**: signal/target shaping
- **Reversal Detector**: signal/target shaping
- **Whipsaw Detector**: dampening / regime behavior
- **Take Profit / MFE lock**: position-management target transform
- **Regime Detector**: context/selector input; can influence Adaptive timeframe and Overseer
- **Watchdog**: operational health gate, NOT an alpha modifier
- **Overseer**: meta-controller, NOT an ordinary target modifier

Current `TargetModifierV3.apply(trader,target)` is probably too narrow for real modifiers. Introduce an explicit immutable `ModifierContextV3` rather than letting modifiers query DB/Saxo themselves. It should carry only needed observations/state: current/previous signal observations, actual inventory, price/entry/MFE where available, timestamps, regime, etc.

Stateful modifiers must key state by trader + recipe/config version + modifier key and remain idempotent per evaluated bar.

## 6. V2 → V3 migration plan

Migrate behavior, not duplicate names.

Suggested decomposition:
- MACD family variants → one MACD base + timeframe/config
- MACD-A → Adaptive MACD base / adaptive timeframe selector with parity test
- MACD Norm → normalized MACD base
- MACD Norm Manager → MACD Norm + MFE/TakeProfit + reversal confirmation + re-entry cooldown/whipsaw controls
- Price + MACD → base strategy
- Price + Stoch → price base plus Stoch timing modifier if behavior remains equivalent
- SFL variants → one SFL base + timeframe/config
- MTF/Cocktail/hybrid experiments → decompose into reusable selector/modifier recipes where behavior is worth preserving
- obsolete shadow/control experiments need not become duplicated production strategies; preserve historical evidence/tests instead

Do not retire a V2 LIVE behavior until its V3 parity test is green and the V3 runtime path is proven.

## 7. MACD-Histogram / MACD-Trailing naming debt

A prior expedient migration rewired the file historically named MACD-Trailing to histogram behavior. Clean this up during registry work rather than perpetuating aliases.

Desired simple MACD-Histogram behavior:
- histogram more positive → add LONG tranche
- histogram less positive → reduce LONG
- histogram more negative → add SHORT tranche
- histogram less negative → reduce SHORT
- natural target crossing/rebuild; no hidden cross confirmation or extra reversal rule

Keep a true Trailing strategy separate if it remains useful.

## 8. Sim-Adapt

`autotrader_v3_sim_adapt_v1.py` now has the selector contract:
- candidate score is external
- minimum evidence
- hysteresis/switch margin
- cooldown

Next step is to feed it real parallel SIM variants. Avoid “last winner chasing.” Score construction should be explicit and auditable (e.g. recent risk-adjusted P/L, drawdown, sample size), and switching should require persistent superiority.

The user's intended behavior: if the currently selected SIM model begins underperforming and another starts performing materially better, Sim-Adapt can switch.

## 9. Overseer and God Mode

Overseer:
- sees market state, indicators, regime, SIM performance, position/capital context
- selects strategy + timeframe + modifiers + settings
- output remains a normal V3 configuration/target path

God Mode:
- bypasses strategy selection
- AI sees the broad observation state and outputs direct `TargetInventoryV3`
- must include confidence/reason and preferably expiry/next-review
- cannot bypass account boundary, capital/risk limits, catastrophe controls or execution invariants
- run in SIM/shadow before granting LIVE authority

Do not pretend the AI implementation exists just because the contracts/UI exist.

## 10. TradingDesk role

TradingDesk should stay minimal for V3:
- V2/V3 motor choice
- V3 LIVE ON/OFF
- current Saxo direction
- worker/runtime status
- eventually a compact summary of active V3 recipe/mode and link to AutoTrader V3

Do not rebuild the full V3 configuration UI inside TradingDesk. The dedicated AutoTrader V3 page is the control room.

## 11. Chart status / current symptom

The user reported chart refresh trouble during this period. A standalone `Live Chart` page was created specifically to isolate chart transport/rendering from TradingDesk.

Known facts from earlier production diagnosis:
- Saxo/chart stream was fresh at ~1 second
- canonical storage is closed 1m bars
- FormingCandleStore provides presentation-only intrabar candle
- Lightweight renderer supports `candles.update(forming)`
- multiple Streamlit refresh approaches were tried
- standalone Live Chart initially crashed because `bar_time` could be a string; PR #497 normalized it

At the end of this chat the user showed a different operational mismatch:
- PriceGauger screenshot: MACD 15m, backend target SHORT, Saxo SHORT, last LIVE evaluation shown as 13:15 UTC
- Saxo screenshot at ~23:10 local showed 5m MACD visually curling/crossing upward
This is not automatically a bug because the PG strategy shown is **15m** while the Saxo screenshot is **5m**, but the evaluation age shown looked stale and should be verified. Do not infer a missed 15m cross from the 5m screenshot.

If investigating, first verify fresh worker/runtime heartbeat and latest closed 15m observation before touching execution logic.

## 12. Open PR cleanup

At handoff creation these old PRs were still open:
- #490 — old V3 modifier controls (TakeProfit/Watchdog/Overseer). This is superseded conceptually by #499/#500/#501. Review then close; do not merge blindly.
- #462 — Middle East Reconstruction Fund, unrelated feature branch; preserve/review separately.
- #440 and #427 — old chart hotfixes; likely superseded by later chart work. Review/close rather than merging stale code.

## 13. Operational workflow

User preference: act as the coder/architect, not a passive advisor. Make the changes, ask for product input only when a real external decision is needed.

When CI is running, keep the thread alive:
1. poll approximately every 15 seconds
2. inspect failures
3. fix/re-run
4. merge only after green
5. follow Railway deploy to terminal SUCCESS/FAILED
6. if failed, inspect logs and continue rather than stopping at “CI is running”

## 14. First recommended Arkitekt 14 sequence

1. Refresh current `main`; inspect commits after this handoff baseline.
2. Close/supersede PR #490 after confirming no unique behavior remains.
3. Build V3 strategy + timeframe runtime dispatch without touching Saxo execution semantics.
4. Make closed-bar driver key include trader + strategy/recipe/config + timeframe; use timezone-aware timestamps and robust datetime comparison.
5. Introduce `ModifierContextV3` and ordered modifier pipeline.
6. Port MACD-Histogram first end-to-end through the new dispatcher with parity tests.
7. Port MACD-A/adaptive behavior next; remove hard-coded 5m.
8. Wire the dedicated V3 page to runtime truth/read-model so UI shows selected vs actually-running recipe.
9. Build real SIM candidate production + Sim-Adapt read model.
10. Only then wire Overseer/God Mode providers, initially SIM/shadow.
11. Move/compose the clean live chart into AutoTrader V3 once runtime truth is solid.
12. Retire V2 pieces incrementally after parity and production proof.

## 15. Definition of “V3 finished enough”

V3 is not finished because the UI exists. It is finished enough for controlled use when:
- one config record unambiguously determines base strategy/timeframe/modifiers/mode
- runtime evaluates exactly that config
- UI reports selected config and actual runtime config with no divergence
- every target transform is auditable
- restart/idempotency is tested
- exact Saxo state reconciliation is preserved
- SIM-Adapt can switch only on explicit evidence/hysteresis
- Overseer/God Mode cannot bypass Risk/Execution
- chart and decision markers reflect the same evaluation clock
- V2 strategy variants can be retired without losing behavior

That is the handoff point.
