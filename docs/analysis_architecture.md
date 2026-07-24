# PriceGauger analysis architecture

## Purpose

PriceGauger shall interpret a market-moving event together with the market's current state and produce a transparent, testable paper-trade proposal. Analysis and action rules must remain separate so both can be evaluated independently.

## Analysis pipeline

```text
Telegram / event stream
        ↓
Direct event interpretation
        +
Saxo multi-timeframe market state
        ↓
Technical interpretation
        ↓
Contextual analysis
        ↓
Historical analogue analysis
        ↓
Transparent final synthesis
        ↓
Paper-trade proposal
        ↓
1h / 4h outcomes + MFE / MAE
        ↓
Versioned evaluation and adjustment
```

## Analysis layers

### 1. Direct event

Interprets the event itself before broader contextual or historical adjustment.

Output should include:

- event direction: LONG, SHORT or NEUTRAL
- confidence
- expected mechanism
- affected assets
- reasons and uncertainty

### 2. Technical

Describes the market's current state from deterministic Saxo OHLCV calculations.

Current inputs:

- 5m, 30m and 1h closed bars
- RSI 14
- MACD 12/26/9
- EMA 20/50
- ATR 14
- volume ratio
- local support and resistance
- swing structure

Current output:

- technical bias
- signal quality
- reversal risk
- market regime
- recommended monitoring interval
- complete indicator rationale

The monitoring interval is an observation recommendation, not a forecast of when the market will reverse.

### 3. Contextual

Optional analysis of the surrounding information environment.

Candidate inputs:

- number of relevant reports
- independent source count
- propagation speed
- syndicated or duplicated reporting
- dominant narratives
- contradictions and speculation
- evidence that the event is already priced in

### 4. Historical

Optional comparison with similar historical events and market reactions.

Historical similarity must distinguish:

- textual or event similarity
- market-regime and contextual similarity

Historical evidence may receive low weight or be explicitly ignored when contextual similarity is weak.

## Separation and transparency rules

- Every layer is stored separately and remains inspectable.
- No layer silently overwrites another.
- Alignment and conflict between layers are explicit outputs.
- The final synthesis shows each layer's contribution.
- Analysis is separate from the paper-trade action rule.
- Rules, thresholds and weights are versioned.
- Insufficient data must be shown as insufficient rather than guessed.

## Final synthesis target

```text
Direct event:       BULLISH · HIGH
Technical:          SLIGHTLY BEARISH · LOW
Contextual:         NOT ANALYSED
Historical:         NOT ANALYSED
Alignment/conflict: CONFLICT

Final assessment:   SLIGHTLY BULLISH
Confidence:         MEDIUM–LOW
Monitoring:         Update within 5 minutes
```

## Paper-trade proposal target

The final assessment may feed a separate simulated action rule that produces:

- LONG, SHORT or NO TRADE
- proposed position size
- maximum leverage
- stop-loss
- take-profit
- maximum holding time
- explicit reasons

The proposal is experimental and must not be treated as an order.

## Evaluation protocol

Current locked protocol: `paper-test-v1`.

- assets: Brent, Gold, Silver and DXY
- directions: LONG, SHORT and NEUTRAL
- entry: first available 5m close at or after the signal
- evaluation horizons: 1h and 4h
- MFE and MAE measured over 4h
- neutral excluded from directional hit rate

Future raw 1m storage may be aggregated into the current 5m protocol. Any formal strategy test performed directly on 1m data requires a new protocol version.

## Next milestone: Combined Direct

Branch: `feature/combined-direct`

Scope is deliberately limited to connecting the existing event interpretation and technical regime.

Required output:

- event bias
- event confidence
- technical bias
- technical signal quality
- alignment or conflict
- combined Direct bias
- combined confidence
- monitoring interval
- transparent reasons

Contextual and Historical analysis are not part of this milestone. They will be connected only after Combined Direct is locally verified and tested.

## Evaluation variants to preserve

The system should eventually compare these variants independently:

1. Direct event baseline
2. Direct event + Technical
3. Direct event + Technical + Contextual
4. Direct event + Technical + Contextual + Historical

This makes it possible to measure whether each added layer improves decisions rather than assuming that additional complexity is beneficial.
