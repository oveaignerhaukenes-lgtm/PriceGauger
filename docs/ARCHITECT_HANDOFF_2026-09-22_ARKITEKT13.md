# Architect handoff — 2026-09-22 — Arkitekt 13

## Immediate state

Production `main` is at merge commit `806d8878eb375cb4f0b150d23f810538649149c4` from PR #438. Railway web for that commit reached SUCCESS.

One follow-up PR is **open and unmerged**:

- **#440 — Hotfix: recover all collapsed live chart panes**
- branch: `architect13/fix-pane-collapse-all-v8`
- head: `0bfd7a968483fad183ec1f5a67239beb3e26fcbe`
- CI run #2704 / `35681834089`: **SUCCESS**
- Ready to merge. User requested this handoff immediately after CI turned green.

## P0 user-visible bug

TradingDesk live chart has valid current data, but graphical series in several panes are effectively invisible.

Latest screenshots:
- price pane: no candlesticks; current/reference price line visible
- MACD pane: renders normally
- RSI pane: reference/separator lines visible, graph effectively absent
- Stochastic pane: same symptom

Temporary browser diagnostics from PR #436 prove the browser has healthy current candle data. Example:

`DBG candles=151 first=1790023560 last=1790045040 OHLC=30588.22/30589.47/30585.97/30586.74`

Displayed last close and bid/ask also update correctly. This is therefore a renderer/pane problem, not a Saxo/canonical-data outage.

## Current root-cause hypothesis

Visual evidence strongly suggests **collapsed Lightweight Charts panes / bad pane-height runtime state**.

MACD has real vertical height. Price, RSI and stochastic appear compressed to separator/reference-line height. That explains why data/reference lines exist while series geometry is invisible.

PR #438 attempted price-pane-only recovery using `setStretchFactor`; it deployed successfully but produced no visible change.

PR #440 generalizes recovery:
- seed all declared panes with usable stretch factors at construction
  - price = 6
  - others = 2
- on every update inspect `pane.getHeight()`
- if a pane is below 24 px, restore its stretch factor
- temporary DBG line reports pane pixel heights as `panes=...`

First CI on #440 failed only because an older regression test asserted the exact previous implementation string. The implementation was not the failure. The stale expectation was updated; CI #2704 is now green.

## Live-chart fix chronology

- **#423** persisted chart view/live payload revisions. Added browser viewport persistence, ~70-candle first-open view, HUD relocation, touch/pinch changes.
- **#428** Oslo renderer hotfix. `direct_runtime_oslo_v2.py` uses brittle exact replacement anchors against `direct_runtime.py`. Any literal changes near those anchors must be checked against Oslo wrapper/tests.
- **#429** preserve visible price series across transient empty canonical refresh.
- **#432** changed viewport persistence from rolling dataset logical indices to timestamp ranges.
- **#433** fixed stale timestamp object suppressing latest-bars fallback.
- **#434** explicitly bound CandlestickSeries to `priceScaleId: 'right'`. No visible change.
- **#435** forced candle Y autoscale after build/update. No visible change.
- **#436** added temporary browser diagnostics. This proved 151 valid OHLC bars are present in-browser.
- **#437** changed candle pane binding to `paneIndex('price')`. No visible change.
- **#438** attempted positive stretch factor on price pane. Merged/deployed; no visible change.
- **#440** current open candidate: recover **all** collapsed panes and report pane pixel heights. CI green.

## Immediate next actions

1. Merge PR #440.
2. Poll Railway until `pricegauger-web` for the merge commit is SUCCESS.
3. Have user refresh.
4. Inspect temporary DBG `panes=...` field.
5. If panes were tiny/zero and recover, root cause confirmed.
6. If pane heights are healthy but price/RSI/stochastic geometry is still absent, stop changing sizing and inspect Lightweight Charts series-to-pane attachment/API behavior directly.
7. Keep DBG until candles and indicator graphics visibly render. Then remove diagnostics in cleanup PR while retaining a regression test.

## Trading/execution state

Do not conflate chart failure with trading authority. User confirmed autotrader became active again while chart remained blank. Current evidence isolates this to presentation/runtime.

Relevant LIVE family in screenshots: **Price + Stoch 2m**.

Earlier Saxo investigation:
- `Amount=-0.02`
- `AmountLong=1.09`
- `AmountShort=1.11`
- net = SHORT 0.02

Resolver correctly uses signed/net exposure rather than stale `OpeningDirection`. Do not change execution semantics as part of chart work.

PR #430 previously made persisted backend controller state authoritative over stale Streamlit session state for Manage/AutoTrade UI truth.

## Safety boundary

Keep chart work isolated from:
- strategy desired-state logic
- Saxo order placement
- close → confirm FLAT → open reconcile
- Position Guard / Watchdog authority

## Relevant files

- `tradingdesk_ui/charts/lightweight/direct_runtime.py`
- `tradingdesk_ui/charts/lightweight/direct_runtime_oslo_v2.py`
- `tradingdesk_ui/charts/lightweight/direct_contract.py`
- `tradingdesk_ui/charts/lightweight/contract.py`
- `pages/0_TradingDesk.py`
- `tests/test_tradingdesk_lightweight_chart_v1.py`

## Railway

Project: `482dad8f-efc5-415a-b1f7-99f45cb2bd7b`
Environment: `9a9b7cc6-1dd0-4044-a0f0-221b06138e8f`

Services:
- web `38f57908-1f7a-40ce-9bf4-abcdf43fe429`
- worker `5267feed-b5cb-4f85-a24a-0c5124664b59`
- stream `0be7cd65-533f-4882-9b81-efeda5b35153`
- Spring engine `254b205b-1633-4c69-aa84-486a0fa6f052`

## Queued product direction after P0 chart stability

Optional deterministic **Adaptive timing / Overseer** around Price+Stoch:
- noise estimator from realized volatility, direction-change rate, wick/body, efficiency ratio, spread
- map regimes to e.g. 1m/2m/3m/5m
- hysteresis + minimum hold time
- timeframe switch must never itself generate LONG/SHORT
- replay-test fixed timeframes vs adaptive before LIVE authority

Do not start until live chart/pane issue is stable.

## Working style

User expects autonomous execution: keep CI/deploy polling alive, fix failures and continue until completion. Ask for input only when external/product judgment is genuinely required.
