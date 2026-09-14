# Live Audio Companion v1

## Goal

Extend the existing read-only Analyst Companion into an eyes-free market companion that can follow several user-selected markets and announce only material changes through the browser/device audio output (including a connected headset).

This is a presentation/monitoring capability. It must not place orders, change AutoTrader state, size positions, or silently mutate Technical Core forecasts.

## User experience

Add a `Live Companion` section with:

- master toggle: `Live Companion på`
- market checkboxes (initially Gold and Silver; architecture must accept other canonical PG markets)
- update categories:
  - `Reversal / trendendring`
  - `HH/HL og LH/LL struktur`
  - `VWAP break / reclaim / rejection`
  - `Momentum (MACD/RSI/exhaustion)`
  - `Support/resistance break + retest`
  - `Cross-market / macro` when canonical inputs are available (DXY, 2Y, 10Y, 30Y, oil)
  - `Warnings` (rapid adverse move, thesis invalidation, unusual volatility)
- sensitivity: Quiet / Normal / Active
- output toggles: `Text`, `Voice`
- optional minimum repeat interval / cooldown

The user can therefore select e.g. Gold + Silver, Reversal + VWAP + Macro + Warnings, Voice on, Normal sensitivity, put on a headset, and leave the chart.

## Alert contract

Do not narrate every candle. Produce an event only when state changes materially. Each event has:

```python
@dataclass(frozen=True)
class CompanionAlertV1:
    alert_id: str
    as_of: datetime
    market: str
    category: str
    severity: str          # INFO | NOTICE | WARNING
    headline: str
    spoken_text: str       # concise, eyes-free sentence(s)
    evidence: tuple[str, ...]
    invalidation: str | None
    dedupe_key: str
```

Typical spoken output:

> Gold: possible reversal strengthening. Price reclaimed VWAP and has now formed a higher low. Ten-year yield and DXY are falling. Watch the previous intraday high for higher-high confirmation.

Warnings should be direct:

> Silver warning: higher-low structure failed and price lost VWAP. The previous bullish reversal interpretation is weakened.

## Architecture

### 1. Deterministic event detector

Create `live_companion_events_v1.py`.

Inputs are persisted/canonical PG snapshots, never scraped UI state. Compare current snapshot with the previous processed snapshot per market and emit typed candidate events. Prefer existing Technical Core fields and deterministic level candidates.

The detector owns facts such as:

- price crossed/reclaimed/lost VWAP
- local structure changed HH/HL/LH/LL when derivable from canonical price history
- deterministic support/resistance candidate was broken/retested
- MACD regime/cross changed
- RSI entered/exited configured zones
- volatility/adverse move exceeded deterministic thresholds
- cross-market factor changed materially when those canonical feeds exist

The detector must not ask an LLM whether a numeric crossing happened.

### 2. Companion interpretation

Reuse the existing Companion provider/runtime for concise interpretation. Feed it the typed event plus bounded current Technical Core context. The LLM may explain significance and combine simultaneous evidence, but may not invent levels or market facts.

For v1, `advice` means analytical guidance such as `reversal not confirmed; watch prior high`. Do not emit personalized buy/sell/order-sizing instructions.

### 3. Event gate and dedupe

Create `live_companion_runtime_v1.py` with session state per selected market:

- last processed snapshot/as_of
- last emitted dedupe keys + timestamps
- current structure/regime state
- alert history (bounded)

Gate candidates by user category selections and sensitivity. Same state must not repeat on Streamlit rerenders. A condition may speak again only after it cleared and re-triggered, materially strengthened/weakened, or cooldown elapsed with a genuinely new snapshot.

### 4. Audio delivery

Create `live_companion_audio_v1.py` and a small browser component. First version should use browser `speechSynthesis` so no server-side audio files are needed. Browser audio naturally routes to the phone/PC's selected headset.

Requirements:

- speech is opt-in and requires an explicit user activation click (browser autoplay policies)
- maintain a client-side queue; never overlap speech
- newest WARNING may drop stale INFO items
- short Norwegian utterances by default; use `nb-NO`/best available Norwegian voice, falling back to default voice
- text alert history remains available even if speech fails
- do not replay old alerts after page reload/reconnect

Later we can replace browser TTS with a higher-quality streaming TTS provider without changing the event contract.

### 5. UI

Create a reusable `render_live_companion_v1(...)` panel rather than binding the feature to one chart page. Persist preferences in Streamlit session initially. Multi-market monitoring must not require changing the chart's selected market.

Recommended compact UI:

```
Live Companion  [ON]
Markets: [x] Gold [x] Silver [ ] Brent
Tell me about: [x] Reversal [x] Structure [x] VWAP [x] Macro [x] Warnings
Sensitivity: Normal
Output: [x] Voice [x] Text
Status: Listening · last update 18:24
```

## Important limitation for first implementation

Streamlit code only runs while a browser session is alive and receiving reruns. Therefore v1 is a live in-app/headset companion, not a guaranteed background phone service. True screen-off/background monitoring and push/audio notifications should be a later server-side worker + notification capability.

## Acceptance criteria

1. User can select Gold and Silver simultaneously.
2. User can independently choose alert categories and sensitivity.
3. A new canonical snapshot can create a deterministic typed event.
4. Same snapshot/rerender cannot produce duplicate speech.
5. A VWAP reclaim/loss and a reversal-structure change can generate concise text + spoken alerts.
6. Alerts include evidence and, where meaningful, invalidation/watch condition.
7. Audio is queued and does not overlap.
8. Disabling Voice immediately prevents subsequent speech while text monitoring may continue.
9. Existing Technical Core, forecast, Saxo and AutoTrader behavior is unchanged.
10. Tests cover detector transitions, category gating, sensitivity, dedupe/cooldown, multi-market isolation and warning priority.

## First implementation slice

Build in this order:

1. deterministic event dataclasses/detector + tests
2. multi-market runtime/dedupe + tests
3. Streamlit selection panel and text alert history
4. browser speech synthesis queue
5. optional Companion/LLM phrasing layer
6. add cross-market macro events once canonical DXY/yield/oil inputs are verified in the current PG data model

This deliberately gets reliable event detection working before adding voice polish or macro claims.