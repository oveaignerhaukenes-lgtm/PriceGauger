# PriceGauger Snapshot Spine v1

## Why

PriceGauger currently contains several correct but expensive reconstruction paths: UI and strategy comparison code may reload canonical history, resample it, recalculate indicators and replay model state when a user merely asks to view a chart. That is increasingly costly as more strategies and analytical layers are added.

The migration principle is:

> **Compute once, persist immutable state, derive many times.**

This is a gradual migration. Canonical market data and the existing Technical Core remain authoritative; no strategy or execution authority is moved by this capability.

## State layers

### 1. Canonical observations

`pg_v2_market_bars_1m` remains the immutable market-data truth. Provider identity is kept outside market bars.

### 2. Feature snapshots

`pg_v2_feature_snapshots` stores one immutable, versioned feature object for one canonical instrument and observed clock.

Identity:

- `instrument_id`
- `as_of`
- `feature_set`
- `feature_set_version`

A changed formula or changed semantic contract must use a new feature-set version. Historical snapshots are never rewritten to make the past look as though the new formula existed then.

The frozen `features_json` object uses stable namespaces:

- `price.*`
- `returns.*`
- `momentum.*`
- `trend.*`
- `volatility.*`
- `activity.*`
- `levels.*`
- `structure.*`
- aggregate `state.*`

Timeframes share the same names. For example, `1m / momentum.macd.histogram` and `30m / momentum.macd.histogram` are the same feature semantic at different clocks.

### 3. Analysis projection

`pg_v2_feature_values` projects the immutable snapshot into long-form rows:

`feature_snapshot_id + timeframe + feature_name -> numeric_value | text_value`

This is deliberately boring. It gives charts, offline learning, regime studies and strategy research one compatible query grammar instead of requiring every model to understand every producer's bespoke JSON shape.

Typical query:

```text
instrument = NAS100
feature = momentum.macd.histogram
timeframe = 1m
start/end = ...
```

The consumer should not recalculate MACD to draw that history.

### 4. Market-state / regime snapshots

Later capabilities should consume feature snapshots and persist their own versioned outputs (regime, cross-market state, event state). They should reference the input snapshot identity/fingerprint rather than silently rebuilding historical inputs.

### 5. Strategy decisions and equity

Every strategy should eventually persist:

- input snapshot identity
- strategy version
- target exposure (`LONG`, `SHORT`, `FLAT`)
- confidence / reason where applicable
- resulting simulated equity point

The strategy-lab chart can then become a read-only query of stored series instead of a replay engine embedded in Streamlit.

## v1 producer

The existing v2 Technical Runtime already computes Technical Core once per cycle and persists `pg_v2_technical_states`. Snapshot Spine v1 reuses that computed object at effectively zero additional analytical cost:

1. Technical Runtime computes from canonical data as before.
2. Existing Technical Core state and forecasts are persisted as before.
3. The exact same in-memory `TechnicalCoreState` is normalized and persisted as a Feature Snapshot.
4. No second indicator calculation is performed.

The feature snapshot clock prefers the newest canonical `1m` snapshot timestamp rather than the slower primary Technical Core timeframe. This lets the persisted spine advance with the observation clock even when aggregate interpretation is anchored to a slower timeframe.

## Migration rules

1. **No big-bang rewrite.** Existing consumers keep working until an explicit bounded cutover.
2. **Persist before consume.** A new read path should first have enough persisted history to be trustworthy.
3. **Version semantics, never history.** Formula changes create a new feature-set/model version.
4. **No execution authority in the snapshot layer.** It observes and stores state only.
5. **Canonical identity everywhere.** Snapshots key on `instrument_id`, not Saxo UIC or display name.
6. **No hidden recomputation in UI once a persisted source exists.** UI should prefer stored series.
7. **Reproducibility over convenience.** AI/model decisions should eventually reference the exact snapshot they consumed.

## Planned gradual cutovers

1. Persist normalized feature snapshots continuously. **(this capability)**
2. Add persisted strategy-equity points for every shadow model.
3. Move the P/L strategy chart to stored equity series.
4. Put AutoManager controls and chart into independent Streamlit fragments.
5. Cache/share one TradingDesk context and one read-only Saxo UI snapshot per UI cycle.
6. Persist versioned regime/state classifications against feature-snapshot IDs.
7. Add regime × strategy outcome queries for the strategy toolbox.
8. Let AI baselines consume exact persisted snapshot IDs and replay the same historical inputs offline.

The end state is not a different PriceGauger. It is the current system progressively becoming a durable event/state store where computation happens in producers and UI/model consumers mostly query already-observed facts.
