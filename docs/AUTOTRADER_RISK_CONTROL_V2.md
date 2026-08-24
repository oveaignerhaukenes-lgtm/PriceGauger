# AutoTrader RiskControl v2

## Authority boundary

RiskControl observes current Saxo LIVE net positions and produces persisted, auditable exit decisions. It never calls Saxo precheck or order endpoints.

The separate close-only executor may consume a RiskControl event only when all execution gates remain valid:

1. Saxo client is explicitly LIVE.
2. Railway code gate is enabled.
3. Database execution motor is armed.
4. The exact current position is explicitly enrolled in Auto-manage.
5. Position identity and trigger basis still match.
6. Current price/tradability checks remain execution-eligible.
7. Saxo precheck is clear and contains no disclaimer.

No automatic entry or position increase exists in this contract.

## Risk semantics

All percentage thresholds use return in the traded product itself:

```text
(current product price - average product open price)
÷ average product open price
× direction
```

They are not percentages of account equity, margin used or movement in the underlying market.

The canonical deployment default is a hard stop at **−2%**. It is only an initialization default: an existing PostgreSQL configuration row is preserved across deployment.

## Persistence ownership

`autotrader_schema_v2.py` owns initialization of:

- risk configuration;
- current risk state;
- immutable risk events;
- exact managed-position enrollment;
- LIVE close configuration;
- LIVE close attempts and reconciliation status.

Runtime startup owns DDL. Streamlit surfaces only read and mutate existing state.

## Audit chain

A close attempt uses the RiskControl event UUID as its identity. The UI joins the attempt to the originating trigger, including trigger reason, product P/L, configured hard stop, trigger time, precheck result, Saxo order id and reconciliation state.

## Compatibility

Existing `pg_v2_autotrader_*` tables and rows are reused. The normalization does not overwrite the active risk configuration and does not change close order payloads, precheck rules, idempotency or uncertainty handling.


## Cadence boundary

The complete Saxo portfolio remains observed every 10 seconds by default. A separate
reaction loop runs every 2 seconds, but it reads active Auto-manage enrollments first
and contacts Saxo only when at least one enrollment exists. Every returned position
must still match the persisted enrollment exactly before evaluation.

Both reaction and LIVE close loops use fixed start-to-start cadence. Saxo request time
therefore consumes part of the interval instead of being added after it. The loops do
not overlap RiskControl state mutation: full-portfolio and managed-only evaluation are
serialized by a process lock.

The Railway stream command declares the 10s portfolio, 2s managed reaction and 2s LIVE
close intervals explicitly. This changes observation latency only; it does not alter
risk thresholds, execution gates, precheck, order payloads, idempotency or reconciliation.
