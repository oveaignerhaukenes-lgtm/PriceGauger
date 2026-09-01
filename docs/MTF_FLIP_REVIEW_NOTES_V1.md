# MTF flip v1 safety review notes

The execution contract is deliberately fail-closed.

- The strategy runtime has no Saxo POST authority; it emits ordinary execution requests only.
- LONG->SHORT and SHORT->LONG can never be encoded as one order. Opposite exposure maps to CLOSE; only observed FLAT maps to OPEN.
- The carried reversal target is persisted from the closed 30m signal and survives the asynchronous close/reconciliation boundary.
- 5m/10m rejection events flatten only and never carry an opposite target.
- A newer closed 30m cross may supersede an uncompleted pending target. If an already-submitted close later settles after such a race, the safe failure mode is FLAT rather than an unverified opposite order.
- Restart adopts actual Saxo exposure with BOOTSTRAP_NO_REPLAY; stale missed bars are cursor-advanced without historical order replay.
- Both LONG and SHORT remain subject to their own Product Admission, current entry authority, Margin Envelope, final Saxo precheck and durable execution-attempt boundary.

Known v1 conservatism: if a newer 30m cross cancels a pending reversal at the same time that the old CLOSE has already crossed its durable submission boundary, the runtime prefers ending FLAT rather than automatically reconstructing the cancelled target. This is intentionally fail-closed and can be refined later with an explicit in-flight-close supersession protocol if live evidence justifies the complexity.
